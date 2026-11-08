"""에이전트 기본 인터페이스. 실제 LLM 호출은 여기에 구현합니다."""

from schema.chat import ChatMessage


class Agent:
    name = "base"

    def run(self, messages: list[ChatMessage]) -> ChatMessage:
        # TODO: LLM 호출로 교체
        last = messages[-1].content if messages else ""
        return ChatMessage(role="assistant", content=f"(echo) {last}")
