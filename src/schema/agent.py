"""agent 공용 데이터 모델."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class ToolSpec(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class Attachment(BaseModel):
    """메시지나 도구 결과에 붙은 파일 (PDF/이미지).

    기록에는 경로만 두고, API 로 보낼 때 파일을 읽어 base64 로 넣습니다.
    """

    path: str
    media_type: str  # application/pdf, image/png, image/jpeg, image/gif, image/webp
    filename: str
    doc_id: int | None = None  # documents 테이블 id (업로드된 문서일 때)

    @property
    def is_pdf(self) -> bool:
        return self.media_type == "application/pdf"


class ToolOutput(BaseModel):
    """도구가 텍스트와 함께 파일을 돌려줄 때 사용. 파일은 모델이 직접 봅니다."""

    text: str
    attachments: list[Attachment] = Field(default_factory=list)


class AgentMessage(BaseModel):
    """대화 한 턴. role="tool" 은 도구 실행 결과."""

    role: Literal["user", "assistant", "tool"]
    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_call_id: str | None = None
    is_error: bool = False
    attachments: list[Attachment] = Field(default_factory=list)  # user / tool 메시지의 파일


StopReason = Literal["end", "tool_use", "max_tokens", "refusal"]


class LLMResponse(BaseModel):
    text: str
    tool_calls: list[ToolCall]
    stop_reason: StopReason
    model: str
    usage: dict[str, int] = Field(default_factory=dict)


class ToolTrace(BaseModel):
    name: str
    arguments: dict[str, Any]
    result: str
    is_error: bool = False


class AgentResult(BaseModel):
    output: str
    stop_reason: StopReason | Literal["max_turns"]
    turns: int
    tool_traces: list[ToolTrace]
    messages: list[AgentMessage]
    trace_id: str | None = None
    workflow_id: str | None = None
