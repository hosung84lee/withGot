"""실행 추적 데이터 모델.

workflow (실행 묶음, 1) ── trace (호출 1회, n) ── span (작업 단위, n)
  - workflow_id: {이름}-{YYYYMMDD-HHMMSS}-{난수}. 예) chat-20261109-223701-a3f9
  - trace_id: 호출마다 새로 생성. 채팅 메시지 1개, 워크플로우 단계 1개, agent 실행 1회 등
"""

from typing import Any, Literal

from pydantic import BaseModel

# "workflow" 는 이전 버전 기록 호환용 (지금은 workflows 테이블에 따로 저장)
SpanKind = Literal["agent", "llm", "tool", "step", "workflow"]
# running: 실행 중 (끝나지 않고 남아 있으면 비정상 종료)
# cancelled: 사용자가 중단 (Streamlit 재실행 등)
SpanStatus = Literal["running", "ok", "warning", "error", "cancelled"]


class SpanRecord(BaseModel):
    """작업 하나. 부모가 없는 span 이 trace(실행 1회)의 루트."""

    id: str
    trace_id: str
    workflow_id: str | None = None
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
    workflow_id: str | None = None
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
        return _worst(self.status, self.errors, self.warnings)


def _worst(status: SpanStatus, errors: int, warnings: int, running: int = 0) -> SpanStatus:
    if status == "error" or errors:
        return "error"
    if status in ("running", "cancelled"):
        return status
    if running:
        return "running"
    if status == "warning" or warnings:
        return "warning"
    return "ok"


class WorkflowRecord(BaseModel):
    """워크플로우 실행 1회 (또는 채팅 대화 1개)."""

    id: str
    name: str
    status: SpanStatus
    started_at: str
    ended_at: str | None = None
    input: Any = None
    output: Any = None
    attributes: dict[str, Any] = {}
    error_type: str | None = None
    error_message: str | None = None
    traceback: str | None = None  # span 밖(워크플로우 코드)에서 난 에러일 때만


class WorkflowSummary(BaseModel):
    """워크플로우 목록 한 줄. 소속 trace 들을 합산."""

    id: str
    name: str
    status: SpanStatus
    started_at: str
    ended_at: str | None
    input_preview: str
    error_messages: str  # 워크플로우와 하위 span 의 에러 메시지 (검색용)
    traces: int
    llm_calls: int
    tool_calls: int
    errors: int
    warnings: int
    running: int
    input_tokens: int
    output_tokens: int

    @property
    def worst_status(self) -> SpanStatus:
        # 워크플로우가 실행 중이면 span 도 실행 중인 게 정상
        running = 0 if self.status == "running" else self.running
        return _worst(self.status, self.errors, self.warnings, running)


class WorkflowPage(BaseModel):
    """워크플로우 검색 결과 한 페이지."""

    items: list[WorkflowSummary]
    total: int  # 조건에 맞는 전체 개수
    page: int  # 1부터 시작 (범위를 넘으면 마지막 페이지로 맞춤)
    page_size: int
    pages: int
