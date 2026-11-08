"""Provider 와 무관한 agent 루프: LLM 호출 → 도구 실행 → 결과 전달 → 반복.

종료 여부는 provider 가 공용 값으로 바꿔 준 stop_reason 으로만 판단합니다.
  tool_use   → 도구 실행 후 다시 호출
  pause      → 그대로 다시 호출 (Claude 서버 도구가 중간에 멈춘 경우)
  end        → 정상 종료
  max_tokens → 응답이 잘림. 잘린 도구 호출은 실행하지 않고 종료
  refusal    → 거절로 종료

실행 과정은 backend.tracing 으로 기록됩니다 (agent → llm / tool span).
"""

from collections.abc import Callable

from agent.providers import LLMProvider, get_provider
from backend.config import get_settings
from backend.tracing import span
from schema.agent import AgentMessage, AgentResult, LLMResponse, ProviderName, ToolTrace
from schema.trace import SpanStatus
from skills import Tool, execute_tool, get_tools

DEFAULT_SYSTEM = (
    "You are a helpful assistant. Use the provided tools when they help answer the user. "
    "When the user refers to uploaded documents that are not attached to the message, "
    "find them with list_uploaded_documents and open them with read_document."
)

# 결과는 나왔지만 확인이 필요한 종료 이유
_WARNING_STOPS = {"max_tokens", "refusal", "max_turns"}


class Agent:
    def __init__(
        self,
        provider: LLMProvider | ProviderName | None = None,
        *,
        model: str | None = None,
        system: str = DEFAULT_SYSTEM,
        tools: list[Tool] | None = None,
        max_turns: int | None = None,
        name: str | None = None,
    ):
        self.provider = (
            provider if isinstance(provider, LLMProvider) else get_provider(provider, model)
        )
        self.system = system
        self.tools = {t.name: t for t in (tools if tools is not None else get_tools())}
        self.max_turns = max_turns or get_settings().agent_max_turns
        self.name = name or f"agent ({self.provider.name})"
        self.last_trace_id: str | None = None  # 실패해도 trace 를 찾을 수 있게

    def run(
        self,
        messages: list[AgentMessage] | str,
        on_event: Callable[[str, dict], None] | None = None,
    ) -> AgentResult:
        history = (
            [AgentMessage(role="user", content=messages)]
            if isinstance(messages, str)
            else list(messages)
        )
        with span(
            "agent",
            self.name,
            input=[m.model_dump(exclude_defaults=True) for m in history],
            provider=self.provider.name,
            model=self.provider.model,
            system=self.system,
            tools=list(self.tools),
            max_turns=self.max_turns,
        ) as s:
            self.last_trace_id = s.trace_id
            result = self._loop(history, on_event or (lambda *_: None))
            result.trace_id = s.trace_id
            s.set(
                output=result.output,
                status="warning" if result.stop_reason in _WARNING_STOPS else None,
                stop_reason=result.stop_reason,
                turns=result.turns,
                tool_calls=len(result.tool_traces),
                tool_errors=sum(t.is_error for t in result.tool_traces),
            )
        return result

    def _loop(self, history: list[AgentMessage], emit: Callable[[str, dict], None]) -> AgentResult:
        specs = [t.spec for t in self.tools.values()]
        traces: list[ToolTrace] = []

        for turn in range(1, self.max_turns + 1):
            resp = self._call_llm(history, specs, turn)
            history.append(self.provider.assistant_message(resp))
            emit("llm", {"turn": turn, "stop_reason": resp.stop_reason, "text": resp.text})

            if resp.stop_reason == "pause":
                continue

            if resp.stop_reason != "tool_use":  # end / max_tokens / refusal
                for c in resp.tool_calls:
                    # 잘린 도구 호출은 실행하지 않음. 결과 없는 호출이 기록에 남으면
                    # 다음 요청이 API 에러가 나므로 에러 결과를 붙여 기록을 유효하게 유지.
                    msg = f"Not executed: response ended with '{resp.stop_reason}'."
                    with span("tool", c.name, input=c.arguments, turn=turn) as ts:
                        ts.set(output=msg, status="warning", tool_call_id=c.id)
                    history.append(
                        AgentMessage(role="tool", content=msg, tool_call_id=c.id, is_error=True)
                    )
                return AgentResult(
                    output=resp.text,
                    stop_reason=resp.stop_reason,
                    turns=turn,
                    tool_traces=traces,
                    messages=history,
                )

            # 한 응답에서 요청된 도구는 모두 실행 (Claude 는 provider 가 한 메시지로 묶음)
            for call in resp.tool_calls:
                with span("tool", call.name, input=call.arguments, turn=turn) as ts:
                    ex = execute_tool(self.tools, call.name, call.arguments)
                    ts.set(output=ex.result, tool_call_id=call.id)
                    if ex.attachments:
                        ts.set(attachments=[a.model_dump() for a in ex.attachments])
                    if ex.is_error:
                        ts.set_error(
                            ex.error_type or "ToolError",
                            ex.error_message or ex.result,
                            ex.traceback,
                        )
                traces.append(
                    ToolTrace(
                        name=call.name,
                        arguments=call.arguments,
                        result=ex.result,
                        is_error=ex.is_error,
                    )
                )
                emit("tool", traces[-1].model_dump())
                history.append(
                    AgentMessage(
                        role="tool",
                        content=ex.result,
                        tool_call_id=call.id,
                        is_error=ex.is_error,
                        attachments=ex.attachments,
                    )
                )

        last = next((m.content for m in reversed(history) if m.role == "assistant"), "")
        return AgentResult(
            output=last,
            stop_reason="max_turns",
            turns=self.max_turns,
            tool_traces=traces,
            messages=history,
        )

    def _call_llm(self, history: list[AgentMessage], specs, turn: int) -> LLMResponse:
        # 요청은 보내기 전에 기록 → API 에러(400 등)가 나도 무엇을 보냈는지 남음
        request = self.provider.build_request(self.system, history, specs)
        with span(
            "llm",
            f"{self.provider.name}:{self.provider.model}",
            input=request,
            turn=turn,
            provider=self.provider.name,
            model=self.provider.model,
        ) as s:
            resp = self.provider.send(request)
            status: SpanStatus | None = (
                "warning" if resp.stop_reason in ("max_tokens", "refusal") else None
            )
            s.set(
                output={
                    "text": resp.text,
                    "thinking": resp.thinking,
                    "tool_calls": [c.model_dump() for c in resp.tool_calls],
                },
                status=status,
                stop_reason=resp.stop_reason,
                usage=resp.usage,
                response_model=resp.model,
            )
        return resp
