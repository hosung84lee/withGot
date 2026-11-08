"""Claude (Anthropic Messages API)."""

from typing import Any

import anthropic

from agent.providers.base import LLMProvider
from backend.attachments import read_base64
from schema.agent import AgentMessage, Attachment, LLMResponse, StopReason, ToolCall, ToolSpec

_STOP_MAP: dict[str, StopReason] = {
    "end_turn": "end",
    "stop_sequence": "end",
    "tool_use": "tool_use",
    "max_tokens": "max_tokens",
    "refusal": "refusal",
    "pause_turn": "pause",
}


def _file_block(a: Attachment) -> dict[str, Any]:
    source = {"type": "base64", "media_type": a.media_type, "data": read_base64(a)}
    if a.is_pdf:
        # PDF 는 페이지를 글자와 이미지로 함께 읽음 (표, 도장, 레이아웃 포함)
        return {"type": "document", "source": source, "title": a.filename}
    return {"type": "image", "source": source}


def _is_tool_results(msg: dict[str, Any]) -> bool:
    return (
        msg["role"] == "user"
        and isinstance(msg["content"], list)
        and all(b.get("type") == "tool_result" for b in msg["content"])
    )


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(
        self,
        model: str,
        max_tokens: int,
        api_key: str | None = None,
        effort: str = "medium",
        fallbacks: bool = True,
        thinking_display: str = "summarized",
    ):
        super().__init__(model, max_tokens)
        self.client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        self.effort = effort
        self.fallbacks = fallbacks
        self.thinking_display = thinking_display

    def _to_api_messages(self, messages: list[AgentMessage]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for m in messages:
            if m.role == "user":
                if m.attachments:  # 파일을 텍스트보다 앞에 두는 것이 권장 순서
                    content = [_file_block(a) for a in m.attachments]
                    content.append(
                        {"type": "text", "text": m.content or "첨부한 파일을 확인해 주세요."}
                    )
                    out.append({"role": "user", "content": content})
                else:
                    out.append({"role": "user", "content": m.content})
            elif m.role == "assistant":
                if m.raw is not None and m.raw_provider == self.name:
                    # thinking 블록 등을 포함한 원본을 그대로 돌려줘야 함
                    content: Any = m.raw
                else:
                    content = [{"type": "text", "text": m.content}] if m.content else []
                    content += [
                        {"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments}
                        for c in m.tool_calls
                    ]
                out.append({"role": "assistant", "content": content})
            else:  # tool 결과: 연속된 결과는 하나의 user 메시지로 묶음
                result: Any = m.content
                if m.attachments:  # Claude 는 도구 결과 안에 PDF/이미지를 직접 넣을 수 있음
                    result = [{"type": "text", "text": m.content}]
                    result += [_file_block(a) for a in m.attachments]
                block = {
                    "type": "tool_result",
                    "tool_use_id": m.tool_call_id,
                    "content": result,
                    "is_error": m.is_error,
                }
                prev = out[-1] if out else None
                if prev and _is_tool_results(prev):
                    prev["content"].append(block)
                else:
                    out.append({"role": "user", "content": [block]})
        return out

    def build_request(
        self, system: str, messages: list[AgentMessage], tools: list[ToolSpec]
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": self._to_api_messages(messages),
            "output_config": {"effort": self.effort},
            # summarized: 추론 요약을 받아 trace 에서 "왜 그렇게 했는지" 확인 (과금 동일)
            "thinking": {"type": "adaptive", "display": self.thinking_display},
            # 대화가 이어질 때마다 같은 파일/기록을 다시 보내므로 캐시로 비용 절감
            "cache_control": {"type": "ephemeral"},
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.parameters}
                for t in tools
            ]
        if self.fallbacks:
            kwargs["betas"] = ["server-side-fallback-2026-07-01"]
            kwargs["fallbacks"] = "default"
        return kwargs

    def send(self, request: dict[str, Any]) -> LLMResponse:
        resp = self.client.beta.messages.create(**request)

        text = "".join(b.text for b in resp.content if b.type == "text")
        thinking = "\n\n".join(
            b.thinking for b in resp.content if b.type == "thinking" and b.thinking
        )
        tool_calls = [
            ToolCall(id=b.id, name=b.name, arguments=b.input or {})
            for b in resp.content
            if b.type == "tool_use"
        ]
        stop = _STOP_MAP.get(resp.stop_reason or "", "end")
        if stop == "refusal":
            category = getattr(resp.stop_details, "category", None) if resp.stop_details else None
            text = text or f"[요청이 거절되었습니다: {category or 'unknown'}]"
        return LLMResponse(
            text=text,
            thinking=thinking,
            tool_calls=tool_calls,
            stop_reason=stop,
            model=resp.model,
            raw=resp.content,
            usage={"input": resp.usage.input_tokens, "output": resp.usage.output_tokens},
        )
