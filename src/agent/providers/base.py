from abc import ABC, abstractmethod
from typing import Any

from schema.agent import AgentMessage, LLMResponse, ProviderName, ToolSpec


class LLMProvider(ABC):
    """LLM 한 번 호출을 담당. 도구 실행 루프는 Agent 가 맡습니다."""

    name: ProviderName

    def __init__(self, model: str, max_tokens: int):
        self.model = model
        self.max_tokens = max_tokens

    @abstractmethod
    def build_request(
        self, system: str, messages: list[AgentMessage], tools: list[ToolSpec]
    ) -> dict[str, Any]:
        """API 에 보낼 요청 본문. 보내기 전에 trace 에 기록할 수 있도록 분리되어 있습니다."""

    @abstractmethod
    def send(self, request: dict[str, Any]) -> LLMResponse:
        """build_request() 결과를 API 로 보내고 공용 응답으로 변환."""

    def complete(
        self, system: str, messages: list[AgentMessage], tools: list[ToolSpec]
    ) -> LLMResponse:
        return self.send(self.build_request(system, messages, tools))

    def assistant_message(self, resp: LLMResponse) -> AgentMessage:
        """응답을 대화 기록용 메시지로 변환 (원본 블록 보존)."""
        return AgentMessage(
            role="assistant",
            content=resp.text,
            tool_calls=resp.tool_calls,
            raw=resp.raw,
            raw_provider=self.name,
        )
