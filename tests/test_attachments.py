"""PDF/이미지 읽기: 1) 메시지 첨부  2) 도구(read_document)로 직접 읽기."""

import base64

import pytest
from anthropic.types.beta import BetaMessage
from openai.types.chat import ChatCompletion

from agent import Agent
from agent.providers import AnthropicProvider, OpenAIProvider
from backend.attachments import attachment_from_document
from backend.storage import save_upload
from backend.tracing import get_trace
from schema.agent import AgentMessage
from schema.document import DocumentKind
from skills import get_tools

PDF = b"%PDF-1.4 fake"
PNG = b"\x89PNG fake"
B64_PDF = base64.standard_b64encode(PDF).decode()
B64_PNG = base64.standard_b64encode(PNG).decode()
DOC_TOOLS = get_tools(["list_uploaded_documents", "read_document"])


@pytest.fixture
def docs():
    pdf = save_upload("계약서.pdf", PDF, DocumentKind.PDF)
    png = save_upload("영수증.png", PNG, DocumentKind.IMAGE)
    return pdf, png


def claude(content, stop):
    return BetaMessage.model_validate(
        {
            "id": "m",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-5-5",
            "content": content,
            "stop_reason": stop,
            "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }
    )


def gpt(message, finish):
    return ChatCompletion.model_validate(
        {
            "id": "c",
            "object": "chat.completion",
            "created": 0,
            "model": "gpt-5.5",
            "choices": [
                {"index": 0, "message": {"role": "assistant", **message}, "finish_reason": finish}
            ],
        }
    )


def fake(provider, client_method, responses):
    calls, it = [], iter(responses)

    def create(**kwargs):
        calls.append(kwargs)
        return next(it)

    obj = (
        provider.client.beta.messages
        if client_method == "claude"
        else provider.client.chat.completions
    )
    obj.create = create
    return calls


# ---------------------------------------------------------------- 1) 메시지 첨부


def test_claude_user_attachments(docs):
    pdf, png = docs
    provider = AnthropicProvider("claude-opus-5-5", 1000, api_key="t")
    calls = fake(provider, "claude", [claude([{"type": "text", "text": "일치"}], "end_turn")])
    msg = AgentMessage(
        role="user",
        content="금액 일치해?",
        attachments=[attachment_from_document(pdf), attachment_from_document(png)],
    )
    Agent(provider, tools=[]).run([msg])

    content = calls[0]["messages"][0]["content"]
    assert content[0] == {
        "type": "document",
        "source": {"type": "base64", "media_type": "application/pdf", "data": B64_PDF},
        "title": "계약서.pdf",
    }
    assert content[1]["type"] == "image" and content[1]["source"]["media_type"] == "image/png"
    assert content[2] == {"type": "text", "text": "금액 일치해?"}  # 파일 뒤에 질문


def test_openai_user_attachments(docs):
    pdf, png = docs
    provider = OpenAIProvider("gpt-5.5", 1000, api_key="t")
    calls = fake(provider, "openai", [gpt({"content": "일치"}, "stop")])
    msg = AgentMessage(
        role="user",
        content="금액 일치해?",
        attachments=[attachment_from_document(pdf), attachment_from_document(png)],
    )
    Agent(provider, tools=[]).run([msg])

    parts = calls[0]["messages"][-1]["content"]
    assert parts[0] == {"type": "text", "text": "금액 일치해?"}
    assert parts[1] == {
        "type": "file",
        "file": {"filename": "계약서.pdf", "file_data": f"data:application/pdf;base64,{B64_PDF}"},
    }
    assert parts[2] == {
        "type": "image_url",
        "image_url": {"url": f"data:image/png;base64,{B64_PNG}"},
    }


# ---------------------------------------------------------------- 2) 도구로 직접 읽기


def test_claude_reads_document_via_tool(docs):
    pdf, _ = docs
    provider = AnthropicProvider("claude-opus-5-5", 1000, api_key="t")
    calls = fake(
        provider,
        "claude",
        [
            claude(
                [
                    {
                        "type": "tool_use",
                        "id": "t1",
                        "name": "read_document",
                        "input": {"doc_id": pdf.id},
                    }
                ],
                "tool_use",
            ),
            claude([{"type": "text", "text": "계약 금액은 100만원"}], "end_turn"),
        ],
    )
    result = Agent(provider, tools=DOC_TOOLS).run("계약서 금액 알려줘")

    assert result.output == "계약 금액은 100만원"
    tool_result = calls[1]["messages"][2]["content"][0]
    assert tool_result["type"] == "tool_result" and tool_result["tool_use_id"] == "t1"
    # Claude 는 도구 결과 안에 PDF 를 그대로 넣음
    assert tool_result["content"][1]["type"] == "document"
    assert tool_result["content"][1]["source"]["data"] == B64_PDF


def test_openai_reads_document_via_tool(docs):
    _, png = docs
    provider = OpenAIProvider("gpt-5.5", 1000, api_key="t")
    tool_call = {
        "id": "call_1",
        "type": "function",
        "function": {"name": "read_document", "arguments": f'{{"doc_id": {png.id}}}'},
    }
    calls = fake(
        provider,
        "openai",
        [
            gpt({"content": None, "tool_calls": [tool_call]}, "tool_calls"),
            gpt({"content": "5천원"}, "stop"),
        ],
    )
    Agent(provider, tools=DOC_TOOLS).run("영수증 금액?")

    msgs = calls[1]["messages"]
    # tool 메시지는 텍스트만, 파일은 바로 뒤 user 메시지로 전달
    assert msgs[-2] == {"role": "tool", "tool_call_id": "call_1", "content": "[첨부: 영수증.png]"}
    assert msgs[-1]["role"] == "user"
    assert msgs[-1]["content"][1]["image_url"]["url"] == f"data:image/png;base64,{B64_PNG}"


def test_read_unknown_document_is_tool_error():
    provider = AnthropicProvider("claude-opus-5-5", 1000, api_key="t")
    fake(
        provider,
        "claude",
        [
            claude(
                [
                    {
                        "type": "tool_use",
                        "id": "t",
                        "name": "read_document",
                        "input": {"doc_id": 999},
                    }
                ],
                "tool_use",
            ),
            claude([{"type": "text", "text": "없네요"}], "end_turn"),
        ],
    )
    result = Agent(provider, tools=DOC_TOOLS).run("999번 읽어줘")
    assert result.tool_traces[0].is_error and "999" in result.tool_traces[0].result


# ---------------------------------------------------------------- trace


def test_trace_stores_file_size_not_base64():
    big = save_upload("big.pdf", b"x" * 300_000, DocumentKind.PDF)
    provider = AnthropicProvider("claude-opus-5-5", 1000, api_key="t")
    fake(provider, "claude", [claude([{"type": "text", "text": "ok"}], "end_turn")])
    msg = AgentMessage(role="user", content="?", attachments=[attachment_from_document(big)])
    result = Agent(provider, tools=[]).run([msg])

    llm = next(s for s in get_trace(result.trace_id) if s.kind == "llm")
    data = llm.input["messages"][0]["content"][0]["source"]["data"]
    assert data.startswith("<base64") and "생략" in data


def test_same_filename_does_not_overwrite():
    a = save_upload("same.pdf", b"first", DocumentKind.PDF)
    b = save_upload("same.pdf", b"second", DocumentKind.PDF)
    assert a.path != b.path and a.filename == b.filename == "same.pdf"
    from pathlib import Path

    assert Path(a.path).read_bytes() == b"first"
