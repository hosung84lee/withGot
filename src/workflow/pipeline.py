"""여러 단계(전처리 → 에이전트 → 후처리)를 묶는 워크플로우."""

from agent import Agent
from schema.agent import AgentMessage, AgentResult, ProviderName


def run_agent(
    messages: list[AgentMessage] | str,
    provider: ProviderName | None = None,
    model: str | None = None,
) -> AgentResult:
    return Agent(provider, model=model).run(messages)
