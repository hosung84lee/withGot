"""trace 기록 테스트. 디버깅에 필요한 정보가 남는지 확인."""

import re

import pytest
from fakes import fake_llm, gpt, tool_call

from agent import Agent
from backend.tracing import (
    get_trace,
    get_workflow,
    list_traces,
    list_workflow_names,
    list_workflows,
    new_workflow_id,
    search_workflows,
    span,
    workflow,
)
from skills import Tool, get_tools
from workflow.mock import STEPS, run_mock_workflow


def test_agent_run_records_full_timeline():
    llm, _ = fake_llm(
        [
            gpt(
                {
                    "content": "시간 도구가 필요함",
                    "tool_calls": [tool_call("c1", "get_current_time", '{"timezone": "UTC"}')],
                },
                "tool_calls",
            ),
            gpt({"content": "완료"}, "stop"),
        ]
    )
    result = Agent(llm=llm, tools=get_tools(["get_current_time"])).run("몇 시야?")
    spans = get_trace(result.trace_id)

    assert [(s.kind, s.status) for s in spans] == [
        ("agent", "ok"),
        ("llm", "ok"),
        ("tool", "ok"),
        ("llm", "ok"),
    ]
    agent, llm1, tool, _ = spans
    assert all(s.parent_id == agent.id for s in spans[1:])
    # LLM: 보낸 요청 원문, 응답, 토큰
    assert llm1.input["model"] == "gpt-6-luna" and llm1.input["messages"][0]["role"] == "system"
    assert llm1.output["text"] == "시간 도구가 필요함"
    assert llm1.output["tool_calls"][0]["name"] == "get_current_time"
    assert llm1.attributes["usage"] == {"input": 100, "output": 20}
    # 도구: 인자와 결과
    assert tool.input == {"timezone": "UTC"} and tool.output.startswith("20")

    [summary] = list_traces()
    assert (summary.llm_calls, summary.tool_calls, summary.input_tokens) == (2, 1, 200)
    assert summary.worst_status == "ok"


def test_api_error_keeps_request_and_traceback():
    llm, _ = fake_llm([RuntimeError("400 bad request")])
    agent = Agent(llm=llm, tools=[], system="")
    with pytest.raises(RuntimeError):
        agent.run("hi")

    agent_span, llm = get_trace(agent.last_trace_id)
    # 에러가 처음 난 LLM span 에 traceback 과 보낸 요청이 남음
    assert llm.status == "error" and "400 bad request" in llm.traceback
    assert llm.input["messages"] == [{"role": "user", "content": "hi"}]
    # 상위 span 에는 traceback 대신 어디서 났는지만
    assert agent_span.status == "error" and agent_span.traceback is None
    assert agent_span.attributes["error_origin"] == "llm:gpt-6-luna"
    assert list_traces()[0].worst_status == "error"


def test_tool_exception_traceback_recorded():
    def broken(x: int) -> str:
        """항상 실패하는 도구"""
        raise ValueError("boom")

    llm, _ = fake_llm(
        [
            gpt(
                {"content": None, "tool_calls": [tool_call("t", "broken", '{"x": 1}')]},
                "tool_calls",
            ),
            gpt({"content": "실패했어요"}, "stop"),
        ]
    )
    result = Agent(llm=llm, tools=[Tool(broken)]).run("go")
    tool = next(s for s in get_trace(result.trace_id) if s.kind == "tool")

    assert tool.status == "error" and tool.error_type == "ValueError"
    assert "raise ValueError" in tool.traceback  # 모델에겐 안 보내지만 trace 엔 남음
    assert list_traces()[0].worst_status == "error"  # 에이전트는 끝났어도 목록에서 🔴


def test_max_tokens_is_warning():
    llm, _ = fake_llm([gpt({"content": "잘린"}, "length")])
    result = Agent(llm=llm, tools=[]).run("hi")
    agent, llm = get_trace(result.trace_id)
    assert agent.status == "warning" and llm.status == "warning"
    assert list_traces()[0].worst_status == "warning"


def test_nested_spans_share_trace_and_long_strings_truncated():
    with span("step", "s1", input={"doc": "x" * 50_000}) as outer, span("step", "s2"):
        pass
    spans = get_trace(outer.trace_id)
    assert [s.name for s in spans] == ["s1", "s2"]
    assert spans[1].parent_id == spans[0].id
    assert "잘림" in spans[0].input["doc"] and len(spans[0].input["doc"]) < 21_000


# ---------------------------------------------------------------- workflow ↔ trace (1:n)


def test_workflow_id_shows_workflow_name():
    wid = new_workflow_id("Mock Workflow")
    assert re.fullmatch(r"mock_workflow-\d{8}-\d{6}-[0-9a-f]{4}", wid)
    assert new_workflow_id("chat").startswith("chat-")


def test_each_call_in_workflow_gets_own_trace():
    llm, _ = fake_llm([gpt({"content": "a"}, "stop"), gpt({"content": "b"}, "stop")])
    with workflow("report", input={"doc": 1}) as wf:
        with span("step", "불러오기") as step:
            pass
        r1 = Agent(llm=llm, tools=[]).run("분석")
        r2 = Agent(llm=llm, tools=[]).run("요약")
        wf.set(output="done")

    assert wf.id.startswith("report-")
    trace_ids = {step.trace_id, r1.trace_id, r2.trace_id}
    assert len(trace_ids) == 3  # 호출마다 새 trace
    assert r1.workflow_id == r2.workflow_id == step.workflow_id == wf.id
    # agent 안의 llm span 도 같은 workflow_id
    assert all(s.workflow_id == wf.id for s in get_trace(r1.trace_id))

    assert [t.trace_id for t in list_traces(wf.id)] == [step.trace_id, r1.trace_id, r2.trace_id]
    [summary] = list_workflows()
    assert (summary.id, summary.traces, summary.llm_calls) == (wf.id, 3, 2)
    assert summary.worst_status == "ok" and summary.input_preview == '{"doc": 1}'
    rec = get_workflow(wf.id)
    assert rec.name == "report" and rec.status == "ok" and rec.output == "done"


def test_run_without_workflow_creates_one_automatically():
    llm, _ = fake_llm([gpt({"content": "ok"}, "stop")])
    r = Agent(llm=llm, tools=[], name="doc-assistant").run("hi")
    assert r.workflow_id.startswith("doc_assistant-")
    assert get_workflow(r.workflow_id).status == "ok"
    assert list_traces(r.workflow_id)[0].trace_id == r.trace_id


def test_chat_reuses_workflow_id_per_message():
    chat_id = new_workflow_id("chat")
    llm, _ = fake_llm([gpt({"content": "1"}, "stop"), RuntimeError("boom")])
    with workflow("chat", workflow_id=chat_id):
        Agent(llm=llm, tools=[]).run("첫 질문")
    with pytest.raises(RuntimeError), workflow("chat", workflow_id=chat_id):
        Agent(llm=llm, tools=[]).run("두 번째 질문")

    [summary] = list_workflows()
    assert summary.id == chat_id and summary.traces == 2
    assert summary.worst_status == "error" and "boom" in summary.error_messages
    assert summary.input_preview.startswith('[{"role": "user", "content": "첫 질문"')
    # 시작 시각은 첫 메시지 기준 유지, 상태는 마지막 메시지 기준
    rec = get_workflow(chat_id)
    assert rec.started_at < rec.ended_at and rec.status == "error"
    assert rec.attributes["error_origin"].startswith("llm:")  # traceback 은 llm span 에만


def test_error_in_workflow_code_outside_spans():
    with pytest.raises(KeyError), workflow("etl") as wf:
        raise KeyError("missing")
    rec = get_workflow(wf.id)
    assert rec.status == "error" and "KeyError" in rec.traceback
    assert list_workflows()[0].worst_status == "error"


def test_mock_workflow_one_trace_per_step():
    result = run_mock_workflow("가나 다라 가나", delay=0)
    assert result.workflow_id.startswith("mock_workflow-")
    traces = list_traces(result.workflow_id)
    assert [t.name for t in traces] == STEPS
    assert [s.trace_id for s in result.steps] == [t.trace_id for t in traces]


def test_old_db_is_migrated(tmp_path, monkeypatch):
    from backend.config import get_settings
    from backend.db import get_connection, init_db

    monkeypatch.setattr(get_settings(), "db_dir", tmp_path / "old")
    with get_connection() as conn:  # workflow_id 컬럼이 없던 예전 구조
        conn.execute(
            """CREATE TABLE spans (id TEXT PRIMARY KEY, trace_id TEXT NOT NULL, parent_id TEXT,
               kind TEXT NOT NULL, name TEXT NOT NULL, status TEXT NOT NULL,
               started_at TEXT NOT NULL, ended_at TEXT, duration_ms INTEGER, input TEXT,
               output TEXT, attributes TEXT, error_type TEXT, error_message TEXT,
               traceback TEXT)"""
        )
        conn.execute(
            "INSERT INTO spans (id, trace_id, kind, name, status, started_at) "
            "VALUES ('t1', 't1', 'workflow', 'mock_workflow', 'ok', '2026-11-01T00:00:00')"
        )
    init_db()
    [w] = list_workflows()
    assert w.id == "legacy-t1" and w.traces == 1
    assert get_trace("t1")[0].workflow_id == "legacy-t1"


def test_tracing_failure_does_not_break_agent(monkeypatch):
    from backend import tracing

    def broken_insert(_):
        raise OSError("disk full")

    monkeypatch.setattr(tracing, "_insert", broken_insert)
    llm, _ = fake_llm([gpt({"content": "ok"}, "stop")])
    assert Agent(llm=llm, tools=[]).run("hi").output == "ok"


# ---------------------------------------------------------------- 워크플로우 검색 / 페이지


def _make_workflows():
    for i in range(25):
        with workflow("mock_workflow", input={"text": f"문서 {i}"}), span("step", "s"):
            pass
    chat_id = new_workflow_id("chat")
    llm, _ = fake_llm([gpt({"content": "환율은 1,400원"}, "stop")])
    with workflow("chat", workflow_id=chat_id):
        Agent(llm=llm, tools=[]).run("오늘 환율 알려줘")
    with pytest.raises(ValueError), workflow("etl"):
        raise ValueError("파일 100%_깨짐")
    return chat_id


def test_paging():
    _make_workflows()
    p1 = search_workflows(page=1, page_size=10)
    p3 = search_workflows(page=3, page_size=10)
    assert (p1.total, p1.pages, len(p1.items), len(p3.items)) == (27, 3, 10, 7)
    assert p1.items[0].name == "etl"  # 최근 활동 순
    ids = [w.id for page in (1, 2, 3) for w in search_workflows(page=page, page_size=10).items]
    assert len(set(ids)) == 27  # 페이지끼리 겹치거나 빠지는 것 없음
    # 범위를 넘는 페이지는 마지막 페이지로
    assert search_workflows(page=99, page_size=10).page == 3
    assert search_workflows(page=0, page_size=10).page == 1


def test_search_by_text_status_and_name():
    chat_id = _make_workflows()
    # 채팅 메시지 내용 (호출의 입력)
    assert [w.id for w in search_workflows(query="환율 알려").items] == [chat_id]
    # 응답 내용 (호출의 출력)
    assert [w.id for w in search_workflows(query="1,400원").items] == [chat_id]
    # workflow ID 일부, 워크플로우 입력
    assert search_workflows(query=chat_id[:12]).total == 1
    assert search_workflows(query="문서 1").total == 11  # 문서 1, 10~19
    # %, _ 는 와일드카드가 아니라 글자 그대로
    assert [w.name for w in search_workflows(query="100%_깨").items] == ["etl"]
    assert search_workflows(query="%").total == 1
    # 상태 (하위 span 포함 가장 나쁜 상태), 종류
    assert [w.name for w in search_workflows(statuses=["error"]).items] == ["etl"]
    assert search_workflows(name="mock_workflow").total == 25
    assert search_workflows(name="mock_workflow", query="문서 2", page_size=5).total == 6
    assert search_workflows(query="없는내용").total == 0
    assert list_workflow_names() == ["chat", "etl", "mock_workflow"]
