"""trace 기록 테스트. 디버깅에 필요한 정보가 남는지 확인."""

import pytest
from anthropic.types.beta import BetaMessage

from agent import Agent
from agent.providers import AnthropicProvider
from backend.tracing import get_trace, list_traces, span
from skills import Tool, get_tools


def _msg(content, stop_reason):
    return BetaMessage.model_validate(
        {
            "id": "msg",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-5-5",
            "content": content,
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": {"input_tokens": 100, "output_tokens": 20},
        }
    )


def _provider(monkeypatch, responses):
    provider = AnthropicProvider("claude-opus-5-5", 1000, api_key="test")
    it = iter(responses)

    def fake_create(**_):
        r = next(it)
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(provider.client.beta.messages, "create", fake_create)
    return provider


def test_agent_run_records_full_timeline(monkeypatch):
    provider = _provider(
        monkeypatch,
        [
            _msg(
                [
                    {"type": "thinking", "thinking": "시간 도구가 필요함", "signature": "sig"},
                    {
                        "type": "tool_use",
                        "id": "tu_1",
                        "name": "get_current_time",
                        "input": {"timezone": "UTC"},
                    },
                ],
                "tool_use",
            ),
            _msg([{"type": "text", "text": "완료"}], "end_turn"),
        ],
    )
    result = Agent(provider, tools=get_tools(["get_current_time"])).run("몇 시야?")
    spans = get_trace(result.trace_id)

    assert [(s.kind, s.status) for s in spans] == [
        ("agent", "ok"),
        ("llm", "ok"),
        ("tool", "ok"),
        ("llm", "ok"),
    ]
    agent, llm1, tool, _ = spans
    assert all(s.parent_id == agent.id for s in spans[1:])
    # LLM: 보낸 요청 원문, 추론 요약, 토큰
    assert llm1.input["model"] == "claude-opus-5-5" and llm1.input["messages"][0]["role"] == "user"
    assert llm1.output["thinking"] == "시간 도구가 필요함"
    assert llm1.attributes["usage"] == {"input": 100, "output": 20}
    # 도구: 인자와 결과
    assert tool.input == {"timezone": "UTC"} and tool.output.startswith("20")

    [summary] = list_traces()
    assert (summary.llm_calls, summary.tool_calls, summary.input_tokens) == (2, 1, 200)
    assert summary.worst_status == "ok"


def test_api_error_keeps_request_and_traceback(monkeypatch):
    provider = _provider(monkeypatch, [RuntimeError("400 bad request")])
    agent = Agent(provider, tools=[])
    with pytest.raises(RuntimeError):
        agent.run("hi")

    agent_span, llm = get_trace(agent.last_trace_id)
    # 에러가 처음 난 LLM span 에 traceback 과 보낸 요청이 남음
    assert llm.status == "error" and "400 bad request" in llm.traceback
    assert llm.input["messages"] == [{"role": "user", "content": "hi"}]
    # 상위 span 에는 traceback 대신 어디서 났는지만
    assert agent_span.status == "error" and agent_span.traceback is None
    assert agent_span.attributes["error_origin"] == "llm:anthropic:claude-opus-5-5"
    assert list_traces()[0].worst_status == "error"


def test_tool_exception_traceback_recorded(monkeypatch):
    def broken(x: int) -> str:
        """항상 실패하는 도구"""
        raise ValueError("boom")

    provider = _provider(
        monkeypatch,
        [
            _msg(
                [{"type": "tool_use", "id": "t", "name": "broken", "input": {"x": 1}}], "tool_use"
            ),
            _msg([{"type": "text", "text": "실패했어요"}], "end_turn"),
        ],
    )
    result = Agent(provider, tools=[Tool(broken)]).run("go")
    tool = next(s for s in get_trace(result.trace_id) if s.kind == "tool")

    assert tool.status == "error" and tool.error_type == "ValueError"
    assert "raise ValueError" in tool.traceback  # 모델에겐 안 보내지만 trace 엔 남음
    assert list_traces()[0].worst_status == "error"  # 에이전트는 끝났어도 목록에서 🔴


def test_max_tokens_is_warning(monkeypatch):
    provider = _provider(monkeypatch, [_msg([{"type": "text", "text": "잘린"}], "max_tokens")])
    result = Agent(provider, tools=[]).run("hi")
    agent, llm = get_trace(result.trace_id)
    assert agent.status == "warning" and llm.status == "warning"
    assert list_traces()[0].worst_status == "warning"


def test_nested_spans_share_trace_and_long_strings_truncated():
    with span("workflow", "wf", input={"doc": "x" * 50_000}) as wf, span("step", "s1"):
        pass
    spans = get_trace(wf.trace_id)
    assert [s.kind for s in spans] == ["workflow", "step"]
    assert spans[1].parent_id == spans[0].id
    assert "잘림" in spans[0].input["doc"] and len(spans[0].input["doc"]) < 21_000


def test_tracing_failure_does_not_break_agent(monkeypatch):
    from backend import tracing

    def broken_insert(_):
        raise OSError("disk full")

    monkeypatch.setattr(tracing, "_insert", broken_insert)
    provider = _provider(monkeypatch, [_msg([{"type": "text", "text": "ok"}], "end_turn")])
    assert Agent(provider, tools=[]).run("hi").output == "ok"
