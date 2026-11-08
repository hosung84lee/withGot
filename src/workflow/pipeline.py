"""여러 단계(전처리 → 에이전트 → 후처리)를 묶는 워크플로우."""

from agent.base import Agent
from schema.chat import ChatMessage


def run_chat(messages: list[ChatMessage], agent: Agent | None = None) -> ChatMessage:
    agent = agent or Agent()
    return agent.run(messages)
