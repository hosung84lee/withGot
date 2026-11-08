"""실행 추적(trace) 데이터 모델."""

from typing import Any, Literal

from pydantic import BaseModel

SpanKind = Literal["workflow", "agent", "llm", "tool", "step"]
# running: 실행 중 (끝나지 않고 남아 있으면 비정상 종료)
# cancelled: 사용자가 중단 (Streamlit 재실행 등)
SpanStatus = Literal["running", "ok", "warning", "error", "cancelled"]


class SpanRecord(BaseModel):
    """작업 하나. 부모가 없는 span 이 trace(실행 1회)의 루트."""

    id: str
    trace_id: str
    parent_id: str | None
    kind: SpanKind
    name: str
    status: SpanStatus
    started_at: str
    ended_at: str | None
    duration_ms: int | None
    input: Any = None
    output: Any = None
    attributes: dict[str, Any] = {}
    error_type: str | None = None
    error_message: str | None = None
    traceback: str | None = None  # 에러가 처음 난 span 에만 저장


class TraceSummary(BaseModel):
    """trace 목록 한 줄."""

    trace_id: str
    kind: SpanKind
    name: str
    status: SpanStatus
    started_at: str
    duration_ms: int | None
    input_preview: str
    error_message: str | None
    llm_calls: int
    tool_calls: int
    errors: int
    warnings: int
    input_tokens: int
    output_tokens: int

    @property
    def worst_status(self) -> SpanStatus:
        """하위 span 까지 포함한 가장 나쁜 상태. 목록에서 문제 있는 실행을 찾는 용도."""
        if self.status == "error" or self.errors:
            return "error"
        if self.status in ("running", "cancelled"):
            return self.status
        if self.status == "warning" or self.warnings:
            return "warning"
        return "ok"
