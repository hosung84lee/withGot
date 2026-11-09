"""agent 루프: LLM 호출 → 도구 실행 → 결과 전달 → 반복.

종료 여부는 OpenAIClient 가 공용 값으로 바꿔 준 stop_reason 으로만 판단합니다.
  tool_use   → 도구 실행 후 다시 호출
  end        → 정상 종료
  max_tokens → 응답이 잘림. 잘린 도구 호출은 실행하지 않고 종료
  refusal    → 거절로 종료

실행 과정은 backend.tracing 으로 기록됩니다. run() 1회 = trace 1개 (agent → llm / tool span).
workflow(...) 안에서 실행하면 그 워크플로우에, 밖에서 실행하면 "agent-..." 워크플로우에 묶입니다.
"""

from collections.abc import Callable

from agent.llm import OpenAIClient
from backend.config import get_settings
from backend.tracing import span
from schema.agent import AgentMessage, AgentResult, LLMResponse, ToolTrace
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
        model: str | None = None,
        *,
        llm: OpenAIClient | None = None,
        system: str = DEFAULT_SYSTEM,
        tools: list[Tool] | None = None,
        max_turns: int | None = None,
        name: str | None = None,
    ):
        self.llm = llm or OpenAIClient(model)
        self.system = system
        self.tools = {t.name: t for t in (tools if tools is not None else get_tools())}
        self.max_turns = max_turns or get_settings().agent_max_turns
        self.name = name or "agent"
        # 실패해서 결과가 없어도 trace 를 찾을 수 있게
        self.last_trace_id: str | None = None
        self.last_workflow_id: str | None = None

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
            model=self.llm.model,
            system=self.system,
            tools=list(self.tools),
            max_turns=self.max_turns,
        ) as s:
            self.last_trace_id, self.last_workflow_id = s.trace_id, s.workflow_id
            result = self._loop(history, on_event or (lambda *_: None))
            result.trace_id, result.workflow_id = s.trace_id, s.workflow_id
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
            history.append(
                AgentMessage(role="assistant", content=resp.text, tool_calls=resp.tool_calls)
            )
            emit("llm", {"turn": turn, "stop_reason": resp.stop_reason, "text": resp.text})

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

            # 한 응답에서 요청된 도구는 모두 실행
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
        request = self.llm.build_request(self.system, history, specs)
        with span("llm", self.llm.model, input=request, turn=turn, model=self.llm.model) as s:
            resp = self.llm.send(request)
            status: SpanStatus | None = (
                "warning" if resp.stop_reason in ("max_tokens", "refusal") else None
            )
            s.set(
                output={
                    "text": resp.text,
                    "tool_calls": [c.model_dump() for c in resp.tool_calls],
                },
                status=status,
                stop_reason=resp.stop_reason,
                usage=resp.usage,
                response_model=resp.model,
            )
        return resp
