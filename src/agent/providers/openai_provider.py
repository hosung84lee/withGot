"""OpenAI Chat Completions API."""

import json
from typing import Any

import openai

from agent.providers.base import LLMProvider
from backend.attachments import read_base64
from schema.agent import AgentMessage, Attachment, LLMResponse, StopReason, ToolCall, ToolSpec

_STOP_MAP: dict[str, StopReason] = {
    "stop": "end",
    "tool_calls": "tool_use",
    "function_call": "tool_use",
    "length": "max_tokens",
    "content_filter": "refusal",
}


def _file_part(a: Attachment) -> dict[str, Any]:
    data_url = f"data:{a.media_type};base64,{read_base64(a)}"
    if a.is_pdf:
        return {"type": "file", "file": {"filename": a.filename, "file_data": data_url}}
    return {"type": "image_url", "image_url": {"url": data_url}}


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self, model: str, max_tokens: int, api_key: str | None = None):
        super().__init__(model, max_tokens)
        self.client = openai.OpenAI(api_key=api_key) if api_key else openai.OpenAI()

    def _to_api_messages(self, system: str, messages: list[AgentMessage]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = [{"role": "system", "content": system}] if system else []
        # OpenAI 의 tool 메시지는 텍스트만 받으므로, 도구가 돌려준 파일은
        # 연속된 tool 메시지가 끝난 직후 user 메시지로 붙여서 보냄
        pending: list[tuple[str, Attachment]] = []

        def flush() -> None:
            if not pending:
                return
            names = "\n".join(f"- {a.filename} (tool_call_id={cid})" for cid, a in pending)
            parts: list[dict[str, Any]] = [
                {"type": "text", "text": f"[도구 결과로 받은 파일]\n{names}"}
            ]
            parts += [_file_part(a) for _, a in pending]
            out.append({"role": "user", "content": parts})
            pending.clear()

        for m in messages:
            if m.role != "tool":
                flush()
            if m.role == "user":
                if m.attachments:
                    parts = [{"type": "text", "text": m.content or "첨부한 파일을 확인해 주세요."}]
                    parts += [_file_part(a) for a in m.attachments]
                    out.append({"role": "user", "content": parts})
                else:
                    out.append({"role": "user", "content": m.content})
            elif m.role == "assistant":
                msg: dict[str, Any] = {"role": "assistant", "content": m.content or None}
                if m.tool_calls:
                    msg["tool_calls"] = [
                        {
                            "id": c.id,
                            "type": "function",
                            "function": {
                                "name": c.name,
                                "arguments": json.dumps(c.arguments, ensure_ascii=False),
                            },
                        }
                        for c in m.tool_calls
                    ]
                out.append(msg)
            else:
                out.append({"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content})
                pending += [(m.tool_call_id or "", a) for a in m.attachments]
        flush()
        return out

    def build_request(
        self, system: str, messages: list[AgentMessage], tools: list[ToolSpec]
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_completion_tokens": self.max_tokens,
            "messages": self._to_api_messages(system, messages),
        }
        if tools:
            kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in tools
            ]
        return kwargs

    def send(self, request: dict[str, Any]) -> LLMResponse:
        resp = self.client.chat.completions.create(**request)
        choice = resp.choices[0]
        msg = choice.message

        tool_calls: list[ToolCall] = []
        for c in msg.tool_calls or []:
            if c.type != "function":
                continue
            try:
                args = json.loads(c.function.arguments or "{}")
            except json.JSONDecodeError:
                # 잘못된 JSON 은 빈 인자로 넘겨 도구 검증 단계에서 에러로 돌려줌
                args = {"__invalid_json__": c.function.arguments}
            tool_calls.append(ToolCall(id=c.id, name=c.function.name, arguments=args))

        usage = {}
        if resp.usage:
            usage = {"input": resp.usage.prompt_tokens, "output": resp.usage.completion_tokens}
        stop = _STOP_MAP.get(choice.finish_reason or "", "end")
        if stop == "end" and tool_calls:
            # tool_choice 로 함수를 강제 지정하면 도구를 호출해도 "stop" 이 올 수 있음
            stop = "tool_use"
        text = msg.content or ""
        if getattr(msg, "refusal", None):
            stop, text = "refusal", msg.refusal
        return LLMResponse(
            text=text,
            tool_calls=tool_calls,
            stop_reason=stop,
            model=resp.model,
            raw=msg,
            usage=usage,
        )
