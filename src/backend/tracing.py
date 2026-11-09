"""실행 추적(trace). agent/workflow 가 무엇을 했는지 SQLite 에 기록합니다.

    workflow (실행 묶음) 1 ── n trace (호출 1회) 1 ── n span (작업 단위)

- workflow: 워크플로우 실행 1회, 또는 채팅 대화 1개.
  id 는 "{이름}-{YYYYMMDD-HHMMSS}-{난수}" 라서 id 만 봐도 어떤 워크플로우인지 알 수 있음.
  예) mock_workflow-20261109-223701-a3f9, chat-20261109-223701-b81c
- trace: 호출 1회. 워크플로우 안에서 부모 없이 시작된 span 마다 새 trace_id 가 생김
  (워크플로우 단계 1개, 채팅 메시지 1개, agent 실행 1회).
- span: 작업 하나 (agent 실행, LLM 호출, 도구 실행, 단계). 실행 흐름을 따라 자동으로 중첩됨.

    with workflow("report", input=...) as wf:          # workflow_id = report-2026...
        with span("step", "문서 불러오기"):              # trace 1
            ...
        Agent(name="analyzer").run(...)                 # trace 2 (agent → llm / tool)
        wf.set(output=...)

워크플로우 밖에서 바로 실행하면 (예: Agent().run) span 이름으로 워크플로우가 자동 생성됩니다.

디버깅을 위한 원칙
- 시작할 때 먼저 기록: 중간에 죽어도 status=running 으로 남아 멈춘 위치가 보임
- 예외는 traceback 과 함께 기록하고 그대로 다시 던짐 (동작을 바꾸지 않음)
- traceback 은 에러가 처음 난 span 에만 저장. 상위 span 에는 어디서 났는지만 표시
- 기록 실패는 경고 로그만 남기고 본 작업을 막지 않음
"""

import json
import logging
import re
import time
import traceback as tb
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from typing import Any

from backend.config import get_settings
from backend.db import get_connection
from schema.trace import (
    SpanKind,
    SpanRecord,
    SpanStatus,
    TraceSummary,
    WorkflowPage,
    WorkflowRecord,
    WorkflowSummary,
)

log = logging.getLogger(__name__)

_current: ContextVar["Span | None"] = ContextVar("current_span", default=None)
_current_workflow: ContextVar["WorkflowRun | None"] = ContextVar("current_workflow", default=None)
_UNSET: Any = object()


def _now() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


def new_workflow_id(name: str) -> str:
    """'{이름}-{YYYYMMDD-HHMMSS}-{난수4}'. 예) chat-20261109-223701-a3f9"""
    slug = re.sub(r"\W+", "_", name).strip("_").lower() or "workflow"
    return f"{slug}-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:4]}"


def _record_exception(rec: "Span | WorkflowRun", e: Exception, label: str) -> None:
    """에러 기록. traceback 은 처음 난 곳에만, 상위에는 어디서 났는지만."""
    rec.status = "error"
    rec.error_type, rec.error_message = type(e).__name__, str(e)
    origin = getattr(e, "_trace_origin", None)
    if origin is None:
        rec.traceback = tb.format_exc()
        _safe(setattr, e, "_trace_origin", label)
    else:
        rec.attributes["error_origin"] = origin


class WorkflowRun:
    """실행 중인 워크플로우. 안에서 시작되는 trace 들이 이 id 로 묶임."""

    def __init__(self, name: str, workflow_id: str | None, input: Any):
        self.id = workflow_id or new_workflow_id(name)
        self.name = name
        self.input = input
        self.output: Any = _UNSET
        self.attributes: dict[str, Any] = {}
        self.status: SpanStatus = "running"
        self.started_at = _now()
        self.ended_at: str | None = None
        self.error_type: str | None = None
        self.error_message: str | None = None
        self.traceback: str | None = None
        self._explicit_status: SpanStatus | None = None

    def set(self, *, output: Any = _UNSET, status: SpanStatus | None = None, **attributes: Any):
        if output is not _UNSET:
            self.output = output
        if status:
            self._explicit_status = status
        self.attributes.update(attributes)


@contextmanager
def workflow(
    name: str, *, input: Any = None, workflow_id: str | None = None
) -> Iterator[WorkflowRun]:
    """워크플로우 실행 묶음. 같은 workflow_id 로 여러 번 열면 같은 워크플로우에 trace 가 쌓임
    (채팅처럼 메시지마다 열고 닫는 경우)."""
    wf = WorkflowRun(name, workflow_id, input)
    enabled = get_settings().tracing_enabled
    if enabled:
        _safe(_upsert_workflow, wf)
    token = _current_workflow.set(wf)
    try:
        yield wf
        wf.status = wf._explicit_status or "ok"
    except Exception as e:
        _record_exception(wf, e, f"workflow:{name}")
        raise
    except BaseException as e:
        wf.status = "cancelled"
        wf.error_type = type(e).__name__
        raise
    finally:
        wf.ended_at = _now()
        _current_workflow.reset(token)
        if enabled:
            _safe(_finish_workflow, wf)


def current_workflow_id() -> str | None:
    wf = _current_workflow.get()
    return wf.id if wf else None


class Span:
    def __init__(
        self,
        kind: SpanKind,
        name: str,
        parent: "Span | None",
        input: Any,
        attributes: dict[str, Any],
    ):
        self.id = uuid.uuid4().hex[:16]
        # 부모가 없으면 새 trace (호출 1회) 시작
        self.trace_id = parent.trace_id if parent else self.id
        self.workflow_id = parent.workflow_id if parent else current_workflow_id()
        self.parent_id = parent.id if parent else None
        self.kind = kind
        self.name = name
        self.input = input
        self.output: Any = None
        self.attributes = attributes
        self.status: SpanStatus = "running"
        self.started_at = _now()
        self.ended_at: str | None = None
        self.duration_ms: int | None = None
        self.error_type: str | None = None
        self.error_message: str | None = None
        self.traceback: str | None = None
        self._explicit_status: SpanStatus | None = None

    def set(self, *, output: Any = _UNSET, status: SpanStatus | None = None, **attributes: Any):
        """결과, 상태, 속성 기록. status 를 안 주면 정상 종료 시 ok."""
        if output is not _UNSET:
            self.output = output
        if status:
            self._explicit_status = status
        self.attributes.update(attributes)

    def set_error(self, error_type: str, message: str, traceback: str | None = None):
        """예외 없이 실패한 경우 (예: 도구가 에러 결과를 반환)."""
        self._explicit_status = "error"
        self.error_type, self.error_message, self.traceback = error_type, message, traceback


@contextmanager
def span(kind: SpanKind, name: str, *, input: Any = None, **attributes: Any) -> Iterator[Span]:
    parent = _current.get()
    if parent is None and _current_workflow.get() is None:
        # 워크플로우 밖에서 바로 실행됨 (예: Agent().run) → 이름으로 워크플로우 자동 생성
        with workflow(name), span(kind, name, input=input, **attributes) as s:
            yield s
        return
    s = Span(kind, name, parent, input, attributes)
    enabled = get_settings().tracing_enabled
    if enabled:
        _safe(_insert, s)
    token = _current.set(s)
    start = time.perf_counter()
    try:
        yield s
        s.status = s._explicit_status or "ok"
    except Exception as e:
        _record_exception(s, e, f"{s.kind}:{s.name}")
        raise
    except BaseException as e:  # Streamlit 재실행/중단, KeyboardInterrupt
        s.status = "cancelled"
        s.error_type = type(e).__name__
        raise
    finally:
        s.duration_ms = int((time.perf_counter() - start) * 1000)
        s.ended_at = _now()
        _current.reset(token)
        if enabled:
            _safe(_update, s)


def current_trace_id() -> str | None:
    s = _current.get()
    return s.trace_id if s else None


# ---------------------------------------------------------------- 저장


def _safe(fn, *args):
    try:
        fn(*args)
    except Exception:
        log.warning("trace 기록 실패", exc_info=True)


def _default(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    return repr(obj)


_BINARY_KEYS = {"data", "file_data"}  # 파일 내용(base64)이 들어가는 키


def _binary_placeholder(v: str) -> str:
    head = v.split(",", 1)[0] + "," if v.startswith("data:") else ""
    return f"{head}<base64 {len(v):,}자 생략>"


def _truncate(obj: Any, limit: int) -> Any:
    """긴 문자열 자르기 + 파일 내용(base64)은 크기만 남김."""
    if isinstance(obj, str) and obj.startswith("data:") and ";base64," in obj[:100]:
        return _binary_placeholder(obj)
    if isinstance(obj, str) and len(obj) > limit:
        return obj[:limit] + f"... [잘림: 총 {len(obj):,}자]"
    if isinstance(obj, dict):
        return {
            k: _binary_placeholder(v)
            if k in _BINARY_KEYS and isinstance(v, str) and len(v) > 1000
            else _truncate(v, limit)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_truncate(v, limit) for v in obj]
    return obj


def _dumps(obj: Any) -> str | None:
    if obj is None:
        return None
    plain = json.loads(json.dumps(obj, ensure_ascii=False, default=_default))
    return json.dumps(_truncate(plain, get_settings().trace_max_str), ensure_ascii=False)


def _insert(s: Span) -> None:
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO spans (id, trace_id, workflow_id, parent_id, kind, name, status,
                                  started_at, input, attributes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                s.id, s.trace_id, s.workflow_id, s.parent_id, s.kind, s.name, s.status,
                s.started_at, _dumps(s.input), _dumps(s.attributes),
            ),
        )  # fmt: skip


def _upsert_workflow(wf: WorkflowRun) -> None:
    # 같은 id 로 다시 열면 (채팅의 다음 메시지) 시작 시각과 입력은 처음 것을 유지
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO workflows (id, name, status, started_at, input, attributes)
               VALUES (?, ?, 'running', ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   status = 'running', ended_at = NULL,
                   error_type = NULL, error_message = NULL, traceback = NULL""",
            (wf.id, wf.name, wf.started_at, _dumps(wf.input), _dumps(wf.attributes)),
        )


def _finish_workflow(wf: WorkflowRun) -> None:
    output = None if wf.output is _UNSET else _dumps(wf.output)
    with get_connection() as conn:
        conn.execute(
            """UPDATE workflows SET status=?, ended_at=?, output=COALESCE(?, output),
                   attributes=json_patch(COALESCE(attributes, '{}'), ?),
                   error_type=?, error_message=?, traceback=?
               WHERE id=?""",
            (
                wf.status, wf.ended_at, output, _dumps(wf.attributes) or "{}",
                wf.error_type, wf.error_message, wf.traceback, wf.id,
            ),
        )  # fmt: skip


def _update(s: Span) -> None:
    with get_connection() as conn:
        conn.execute(
            """UPDATE spans SET status=?, ended_at=?, duration_ms=?, output=?, attributes=?,
                                error_type=?, error_message=?, traceback=?
               WHERE id=?""",
            (
                s.status, s.ended_at, s.duration_ms, _dumps(s.output), _dumps(s.attributes),
                s.error_type, s.error_message, s.traceback, s.id,
            ),
        )  # fmt: skip


# ---------------------------------------------------------------- 조회


def _loads(v: str | None) -> Any:
    return json.loads(v) if v else None


def _preview(v: Any, n: int = 80) -> str:
    if v is None:
        return ""
    text = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n] + "…"


# 워크플로우별 합산 + 가장 나쁜 상태 (WorkflowSummary.worst_status 와 같은 규칙)
_WORKFLOW_AGG = """
WITH agg AS (
    SELECT w.id, w.name, w.status, w.started_at, w.ended_at, w.rowid AS rid,
           COALESCE(w.input, (SELECT r.input FROM spans r
                              WHERE r.workflow_id = w.id AND r.parent_id IS NULL
                              ORDER BY r.started_at, r.rowid LIMIT 1)) AS input,
           COALESCE(w.error_message, '') || ' ' ||
               COALESCE(GROUP_CONCAT(DISTINCT s.error_message), '') AS error_messages,
           COUNT(DISTINCT s.trace_id)                             AS traces,
           COALESCE(SUM(s.kind = 'llm'), 0)                       AS llm_calls,
           COALESCE(SUM(s.kind = 'tool'), 0)                      AS tool_calls,
           COALESCE(SUM(s.status = 'error'), 0)                   AS errors,
           COALESCE(SUM(s.status = 'warning'), 0)                 AS warnings,
           COALESCE(SUM(s.status IN ('running', 'cancelled')), 0) AS running,
           COALESCE(SUM(json_extract(s.attributes, '$.usage.input')), 0)  AS input_tokens,
           COALESCE(SUM(json_extract(s.attributes, '$.usage.output')), 0) AS output_tokens
    FROM workflows w LEFT JOIN spans s ON s.workflow_id = w.id
    GROUP BY w.id
),
ranked AS (
    SELECT *,
           CASE
               WHEN status = 'error' OR errors > 0 THEN 'error'
               WHEN status IN ('running', 'cancelled') THEN status
               WHEN running > 0 THEN 'running'
               WHEN status = 'warning' OR warnings > 0 THEN 'warning'
               ELSE 'ok'
           END AS worst
    FROM agg
)
"""

# 검색 대상: workflow ID, 이름, 입력, 에러 메시지, 소속 호출들의 입력/출력 (채팅 메시지 등)
_SEARCH = """(
    id LIKE :q ESCAPE '\\' OR name LIKE :q ESCAPE '\\' OR input LIKE :q ESCAPE '\\'
    OR error_messages LIKE :q ESCAPE '\\'
    OR EXISTS (SELECT 1 FROM spans r
               WHERE r.workflow_id = ranked.id AND r.parent_id IS NULL
                 AND (r.input LIKE :q ESCAPE '\\' OR r.output LIKE :q ESCAPE '\\'))
)"""


def _like(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def search_workflows(
    *,
    query: str | None = None,
    statuses: list[SpanStatus] | None = None,
    name: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> WorkflowPage:
    """워크플로우 검색 + 페이지 나누기. 최근 활동 순.

    query: workflow ID, 이름, 입력, 에러 메시지, 채팅 메시지 등에서 부분 일치 (대소문자 무시)
    statuses: 가장 나쁜 상태(하위 span 포함) 기준. 예) ["error"]
    name: 워크플로우 종류 (chat, mock_workflow 등) 정확히 일치
    """
    where, params = ["1 = 1"], {}
    if query and query.strip():
        where.append(_SEARCH)
        params["q"] = _like(query.strip())
    if statuses:
        keys = [f"st{i}" for i in range(len(statuses))]
        where.append(f"worst IN ({', '.join(':' + k for k in keys)})")
        params.update(zip(keys, statuses, strict=True))
    if name:
        where.append("name = :name")
        params["name"] = name
    cond = " AND ".join(where)  # 조건 문자열은 고정, 값은 모두 파라미터로 전달

    page_size = max(1, page_size)
    with get_connection() as conn:
        total = conn.execute(
            f"{_WORKFLOW_AGG} SELECT COUNT(*) FROM ranked WHERE {cond}", params
        ).fetchone()[0]
        pages = max(1, -(-total // page_size))
        page = min(max(1, page), pages)
        rows = conn.execute(
            f"""{_WORKFLOW_AGG}
            SELECT * FROM ranked WHERE {cond}
            ORDER BY COALESCE(ended_at, started_at) DESC, rid DESC
            LIMIT :limit OFFSET :offset""",
            {**params, "limit": page_size, "offset": (page - 1) * page_size},
        ).fetchall()
    items = [
        WorkflowSummary(**{**dict(r), "input_preview": _preview(_loads(r["input"]))}) for r in rows
    ]
    return WorkflowPage(items=items, total=total, page=page, page_size=page_size, pages=pages)


def list_workflows(limit: int = 100) -> list[WorkflowSummary]:
    """최근 워크플로우 목록 (소속 trace 들을 합산)."""
    return search_workflows(page_size=limit).items


def get_workflow_summary(workflow_id: str) -> WorkflowSummary | None:
    """워크플로우 1개의 합산 정보 (목록의 현재 페이지에 없을 때 사용)."""
    with get_connection() as conn:
        r = conn.execute(
            f"{_WORKFLOW_AGG} SELECT * FROM ranked WHERE id = ?", (workflow_id,)
        ).fetchone()
    if r is None:
        return None
    return WorkflowSummary(**{**dict(r), "input_preview": _preview(_loads(r["input"]))})


def list_workflow_names() -> list[str]:
    """기록된 워크플로우 종류 (검색 필터용)."""
    with get_connection() as conn:
        rows = conn.execute("SELECT DISTINCT name FROM workflows ORDER BY name").fetchall()
    return [r["name"] for r in rows]


def get_workflow(workflow_id: str) -> WorkflowRecord | None:
    with get_connection() as conn:
        r = conn.execute("SELECT * FROM workflows WHERE id = ?", (workflow_id,)).fetchone()
    if r is None:
        return None
    return WorkflowRecord(
        **{
            **dict(r),
            "input": _loads(r["input"]),
            "output": _loads(r["output"]),
            "attributes": _loads(r["attributes"]) or {},
        }
    )


def list_traces(workflow_id: str | None = None, limit: int = 100) -> list[TraceSummary]:
    """trace(호출 1회) 목록. workflow_id 를 주면 그 워크플로우의 trace 만 시작 순서대로."""
    where, params, order = "", [], "DESC"
    if workflow_id:
        where, params, order = "AND r.workflow_id = ?", [workflow_id], "ASC"
    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT r.trace_id, r.workflow_id, r.kind, r.name, r.status, r.started_at, r.duration_ms,
                   r.input, r.error_message,
                   SUM(s.kind = 'llm')        AS llm_calls,
                   SUM(s.kind = 'tool')       AS tool_calls,
                   SUM(s.status = 'error')    AS errors,
                   SUM(s.status = 'warning')  AS warnings,
                   SUM(COALESCE(json_extract(s.attributes, '$.usage.input'), 0))  AS input_tokens,
                   SUM(COALESCE(json_extract(s.attributes, '$.usage.output'), 0)) AS output_tokens
            FROM spans r JOIN spans s ON s.trace_id = r.trace_id
            WHERE r.parent_id IS NULL {where}
            GROUP BY r.id
            ORDER BY r.started_at {order}, r.rowid {order}  -- 같은 ms 면 기록 순서
            LIMIT ?
            """,  # where/order 는 고정 문자열 (사용자 입력 아님)
            (*params, limit),
        ).fetchall()
    return [
        TraceSummary(**{**dict(r), "input_preview": _preview(_loads(r["input"]))}) for r in rows
    ]


def get_trace(trace_id: str) -> list[SpanRecord]:
    """trace 의 모든 span 을 시작 순서대로."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM spans WHERE trace_id = ? ORDER BY rowid", (trace_id,)
        ).fetchall()
    return [
        SpanRecord(
            **{
                **dict(r),
                "input": _loads(r["input"]),
                "output": _loads(r["output"]),
                "attributes": _loads(r["attributes"]) or {},
            }
        )
        for r in rows
    ]


def delete_all_traces() -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM spans")
        conn.execute("DELETE FROM workflows")
