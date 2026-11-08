from agent.providers.anthropic_provider import AnthropicProvider
from agent.providers.base import LLMProvider
from agent.providers.openai_provider import OpenAIProvider
from backend.config import get_settings
from schema.agent import ProviderName


def get_provider(name: ProviderName | None = None, model: str | None = None) -> LLMProvider:
    s = get_settings()
    name = name or s.default_provider
    if name == "anthropic":
        return AnthropicProvider(
            model=model or s.anthropic_model,
            max_tokens=s.agent_max_tokens,
            api_key=s.anthropic_api_key,
            effort=s.anthropic_effort,
            fallbacks=s.anthropic_fallbacks,
            thinking_display=s.anthropic_thinking_display,
        )
    if name == "openai":
        return OpenAIProvider(
            model=model or s.openai_model, max_tokens=s.agent_max_tokens, api_key=s.openai_api_key
        )
    raise ValueError(f"Unknown provider: {name}")


__all__ = [
    "AnthropicProvider",
    "LLMProvider",
    "OpenAIProvider",
    "get_provider",
]
