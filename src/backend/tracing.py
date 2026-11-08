"""실행 추적(trace). agent/workflow 가 무엇을 했는지 SQLite 에 기록합니다.

span 하나 = 작업 하나 (workflow, agent 실행, LLM 호출, 도구 실행, 단계).
span 은 실행 흐름을 따라 자동으로 부모-자식으로 중첩되고,
부모가 없는 span 이 trace(실행 1회)의 루트가 됩니다.

    with span("agent", "my agent", input=...) as s:
        with span("llm", "anthropic:claude-opus-5-5", input=request) as llm:
            ...
            llm.set(output=..., stop_reason="end", usage={...})

디버깅을 위한 원칙
- 시작할 때 먼저 기록: 중간에 죽어도 status=running 으로 남아 멈춘 위치가 보임
- 예외는 traceback 과 함께 기록하고 그대로 다시 던짐 (동작을 바꾸지 않음)
- traceback 은 에러가 처음 난 span 에만 저장. 상위 span 에는 어디서 났는지만 표시
- 기록 실패는 경고 로그만 남기고 본 작업을 막지 않음
"""

import json
import logging
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
from schema.trace import SpanKind, SpanRecord, SpanStatus, TraceSummary

log = logging.getLogger(__name__)

_current: ContextVar["Span | None"] = ContextVar("current_span", default=None)
_UNSET: Any = object()


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
        self.trace_id = parent.trace_id if parent else self.id
        self.parent_id = parent.id if parent else None
        self.kind = kind
        self.name = name
        self.input = input
        self.output: Any = None
        self.attributes = attributes
        self.status: SpanStatus = "running"
        self.started_at = datetime.now().isoformat(timespec="milliseconds")
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
    s = Span(kind, name, _current.get(), input, attributes)
    enabled = get_settings().tracing_enabled
    if enabled:
        _safe(_insert, s)
    token = _current.set(s)
    start = time.perf_counter()
    try:
        yield s
        s.status = s._explicit_status or "ok"
    except Exception as e:
        s.status = "error"
        s.error_type, s.error_message = type(e).__name__, str(e)
        origin = getattr(e, "_trace_origin", None)
        if origin is None:
            s.traceback = tb.format_exc()
            _safe(setattr, e, "_trace_origin", f"{s.kind}:{s.name}")
        else:
            s.attributes["error_origin"] = origin
        raise
    except BaseException as e:  # Streamlit 재실행/중단, KeyboardInterrupt
        s.status = "cancelled"
        s.error_type = type(e).__name__
        raise
    finally:
        s.duration_ms = int((time.perf_counter() - start) * 1000)
        s.ended_at = datetime.now().isoformat(timespec="milliseconds")
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


_BINARY_KEYS = {"data", "file_data"}  # Claude source.data / OpenAI file.file_data


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
            """INSERT INTO spans (id, trace_id, parent_id, kind, name, status, started_at,
                                  input, attributes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                s.id, s.trace_id, s.parent_id, s.kind, s.name, s.status, s.started_at,
                _dumps(s.input), _dumps(s.attributes),
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


def list_traces(limit: int = 100) -> list[TraceSummary]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT r.trace_id, r.kind, r.name, r.status, r.started_at, r.duration_ms,
                   r.input, r.error_message,
                   SUM(s.kind = 'llm')        AS llm_calls,
                   SUM(s.kind = 'tool')       AS tool_calls,
                   SUM(s.status = 'error')    AS errors,
                   SUM(s.status = 'warning')  AS warnings,
                   SUM(COALESCE(json_extract(s.attributes, '$.usage.input'), 0))  AS input_tokens,
                   SUM(COALESCE(json_extract(s.attributes, '$.usage.output'), 0)) AS output_tokens
            FROM spans r JOIN spans s ON s.trace_id = r.trace_id
            WHERE r.parent_id IS NULL
            GROUP BY r.id
            ORDER BY r.started_at DESC
            LIMIT ?
            """,
            (limit,),
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
