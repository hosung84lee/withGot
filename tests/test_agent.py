"""API 키 없이 agent 루프와 provider 변환 로직을 검증하는 테스트.

SDK 의 create() 를 가짜 응답으로 바꿔치기해서 실제 네트워크 호출은 하지 않습니다.
"""

import anthropic
import openai
from anthropic.types.beta import BetaMessage
from openai.types.chat import ChatCompletion

from agent import Agent
from agent.providers import AnthropicProvider, OpenAIProvider
from skills import get_tools

TOOLS = get_tools(["get_current_time"])


def test_tool_schema():
    spec = TOOLS[0].spec
    assert spec.name == "get_current_time"
    assert spec.parameters["properties"]["timezone"]["default"] == "Asia/Seoul"
    assert spec.parameters["additionalProperties"] is False


def _claude_msg(content, stop_reason):
    return BetaMessage.model_validate(
        {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-5-5",
            "content": content,
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
    )


def test_anthropic_tool_loop(monkeypatch):
    responses = iter(
        [
            _claude_msg(
                [
                    {"type": "text", "text": "시간을 확인할게요."},
                    {
                        "type": "tool_use",
                        "id": "tu_1",
                        "name": "get_current_time",
                        "input": {"timezone": "UTC"},
                    },
                ],
                "tool_use",
            ),
            _claude_msg([{"type": "text", "text": "지금은 UTC 기준 오후입니다."}], "end_turn"),
        ]
    )
    calls = []
    provider = AnthropicProvider("claude-opus-5-5", 1000, api_key="test")

    def fake_create(**kwargs):
        calls.append(kwargs)
        return next(responses)

    monkeypatch.setattr(provider.client.beta.messages, "create", fake_create)
    result = Agent(provider, tools=TOOLS).run("지금 몇 시야?")

    assert result.output == "지금은 UTC 기준 오후입니다."
    assert result.turns == 2 and result.stop_reason == "end"
    assert result.tool_traces[0].name == "get_current_time" and not result.tool_traces[0].is_error
    # 두 번째 요청: assistant 원본 블록 + tool_result 를 담은 user 메시지
    second = calls[1]
    assert second["fallbacks"] == "default"
    assert second["output_config"] == {"effort": "medium"}
    assert second["tools"][0]["input_schema"]["type"] == "object"
    assistant, tool_msg = second["messages"][1], second["messages"][2]
    assert assistant["role"] == "assistant" and assistant["content"][1].type == "tool_use"
    assert tool_msg == {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": "tu_1",
                "content": result.tool_traces[0].result,
                "is_error": False,
            }
        ],
    }


def test_anthropic_refusal(monkeypatch):
    provider = AnthropicProvider("claude-opus-5-5", 1000, api_key="test")
    monkeypatch.setattr(
        provider.client.beta.messages, "create", lambda **_: _claude_msg([], "refusal")
    )
    result = Agent(provider, tools=TOOLS).run("...")
    assert result.stop_reason == "refusal" and "거절" in result.output


def _openai_msg(message, finish_reason):
    return ChatCompletion.model_validate(
        {
            "id": "c1",
            "object": "chat.completion",
            "created": 0,
            "model": "gpt-5.5",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", **message},
                    "finish_reason": finish_reason,
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
    )


def test_openai_tool_loop_with_bad_args(monkeypatch):
    responses = iter(
        [
            _openai_msg(
                {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "get_current_time", "arguments": '{"tz": "UTC"}'},
                        },
                    ],
                },
                "tool_calls",
            ),
            _openai_msg({"content": "완료"}, "stop"),
        ]
    )
    calls = []
    provider = OpenAIProvider("gpt-5.5", 1000, api_key="test")

    def fake_create(**kwargs):
        calls.append(kwargs)
        return next(responses)

    monkeypatch.setattr(provider.client.chat.completions, "create", fake_create)
    result = Agent(provider, tools=TOOLS, system="sys").run("몇 시야?")

    assert result.output == "완료"
    # 잘못된 인자는 예외 대신 에러 결과로 모델에게 돌려줌
    assert result.tool_traces[0].is_error
    msgs = calls[1]["messages"]
    assert msgs[0] == {"role": "system", "content": "sys"}
    assert msgs[2]["tool_calls"][0]["function"]["name"] == "get_current_time"
    assert msgs[3]["role"] == "tool" and msgs[3]["tool_call_id"] == "call_1"


def test_max_turns(monkeypatch):
    provider = OpenAIProvider("gpt-5.5", 1000, api_key="test")
    loop = _openai_msg(
        {
            "content": None,
            "tool_calls": [
                {
                    "id": "c",
                    "type": "function",
                    "function": {"name": "get_current_time", "arguments": "{}"},
                },
            ],
        },
        "tool_calls",
    )
    monkeypatch.setattr(provider.client.chat.completions, "create", lambda **_: loop)
    result = Agent(provider, tools=TOOLS, max_turns=3).run("hi")
    assert result.stop_reason == "max_turns" and len(result.tool_traces) == 3


def test_sdk_clients_constructed():
    assert isinstance(AnthropicProvider("m", 1, api_key="x").client, anthropic.Anthropic)
    assert isinstance(OpenAIProvider("m", 1, api_key="x").client, openai.OpenAI)


def test_anthropic_max_tokens_does_not_run_truncated_tool(monkeypatch):
    provider = AnthropicProvider("claude-opus-5-5", 1000, api_key="test")
    truncated = _claude_msg(
        [{"type": "tool_use", "id": "tu_1", "name": "get_current_time", "input": {}}],
        "max_tokens",
    )
    monkeypatch.setattr(provider.client.beta.messages, "create", lambda **_: truncated)
    result = Agent(provider, tools=TOOLS).run("hi")

    assert result.stop_reason == "max_tokens" and result.turns == 1
    assert result.tool_traces == []  # 잘린 도구는 실행하지 않음
    # 결과 없는 tool_use 가 남지 않도록 에러 결과가 붙어 있어야 다음 요청이 유효함
    last = result.messages[-1]
    assert last.role == "tool" and last.tool_call_id == "tu_1" and last.is_error


def test_openai_length_does_not_run_truncated_tool(monkeypatch):
    provider = OpenAIProvider("gpt-5.5", 1000, api_key="test")
    truncated = _openai_msg(
        {
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "get_current_time", "arguments": '{"timez'},
                },
            ],
        },
        "length",
    )
    monkeypatch.setattr(provider.client.chat.completions, "create", lambda **_: truncated)
    result = Agent(provider, tools=TOOLS).run("hi")
    assert result.stop_reason == "max_tokens" and result.tool_traces == []
    assert result.messages[-1].role == "tool"


def test_openai_stop_with_tool_calls_is_tool_use(monkeypatch):
    # tool_choice 강제 지정 시 finish_reason 이 "stop" 이어도 도구 호출로 처리
    responses = iter(
        [
            _openai_msg(
                {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "c",
                            "type": "function",
                            "function": {"name": "get_current_time", "arguments": "{}"},
                        },
                    ],
                },
                "stop",
            ),
            _openai_msg({"content": "끝"}, "stop"),
        ]
    )
    provider = OpenAIProvider("gpt-5.5", 1000, api_key="test")
    monkeypatch.setattr(provider.client.chat.completions, "create", lambda **_: next(responses))
    result = Agent(provider, tools=TOOLS).run("hi")
    assert result.output == "끝" and len(result.tool_traces) == 1
