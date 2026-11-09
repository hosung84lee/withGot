"""PDF/이미지 읽기: 1) 메시지 첨부  2) 도구(read_document)로 직접 읽기."""

import base64
from pathlib import Path

import pytest
from fakes import fake_llm, gpt, tool_call

from agent import Agent
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


# ---------------------------------------------------------------- 1) 메시지 첨부


def test_user_attachments(docs):
    pdf, png = docs
    llm, calls = fake_llm([gpt({"content": "일치"}, "stop")])
    msg = AgentMessage(
        role="user",
        content="금액 일치해?",
        attachments=[attachment_from_document(pdf), attachment_from_document(png)],
    )
    Agent(llm=llm, tools=[]).run([msg])

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


def test_reads_document_via_tool(docs):
    _, png = docs
    llm, calls = fake_llm(
        [
            gpt(
                {
                    "content": None,
                    "tool_calls": [tool_call("call_1", "read_document", f'{{"doc_id": {png.id}}}')],
                },
                "tool_calls",
            ),
            gpt({"content": "5천원"}, "stop"),
        ]
    )
    result = Agent(llm=llm, tools=DOC_TOOLS).run("영수증 금액?")

    assert result.output == "5천원"
    msgs = calls[1]["messages"]
    # tool 메시지는 텍스트만, 파일은 바로 뒤 user 메시지로 전달
    assert msgs[-2] == {"role": "tool", "tool_call_id": "call_1", "content": "[첨부: 영수증.png]"}
    assert msgs[-1]["role"] == "user"
    assert msgs[-1]["content"][1]["image_url"]["url"] == f"data:image/png;base64,{B64_PNG}"


def test_read_unknown_document_is_tool_error():
    llm, _ = fake_llm(
        [
            gpt(
                {
                    "content": None,
                    "tool_calls": [tool_call("t", "read_document", '{"doc_id": 999}')],
                },
                "tool_calls",
            ),
            gpt({"content": "없네요"}, "stop"),
        ]
    )
    result = Agent(llm=llm, tools=DOC_TOOLS).run("999번 읽어줘")
    assert result.tool_traces[0].is_error and "999" in result.tool_traces[0].result


# ---------------------------------------------------------------- trace


def test_trace_stores_file_size_not_base64():
    big = save_upload("big.pdf", b"x" * 300_000, DocumentKind.PDF)
    llm, _ = fake_llm([gpt({"content": "ok"}, "stop")])
    msg = AgentMessage(role="user", content="?", attachments=[attachment_from_document(big)])
    result = Agent(llm=llm, tools=[]).run([msg])

    span = next(s for s in get_trace(result.trace_id) if s.kind == "llm")
    data = span.input["messages"][-1]["content"][1]["file"]["file_data"]
    assert data.startswith("data:application/pdf;base64,<base64") and "생략" in data


def test_same_filename_does_not_overwrite():
    a = save_upload("same.pdf", b"first", DocumentKind.PDF)
    b = save_upload("same.pdf", b"second", DocumentKind.PDF)
    assert a.path != b.path and a.filename == b.filename == "same.pdf"
    assert Path(a.path).read_bytes() == b"first"
