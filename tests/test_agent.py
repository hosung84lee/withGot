"""agent 루프와 OpenAI 요청 변환 로직 테스트 (API 키 불필요)."""

import openai
from fakes import fake_llm, gpt, tool_call

from agent import Agent, OpenAIClient
from skills import get_tools

TOOLS = get_tools(["get_current_time"])


def test_tool_schema():
    spec = TOOLS[0].spec
    assert spec.name == "get_current_time"
    assert spec.parameters["properties"]["timezone"]["default"] == "Asia/Seoul"
    assert spec.parameters["additionalProperties"] is False


def test_tool_loop(monkeypatch):
    llm, calls = fake_llm(
        [
            gpt(
                {
                    "content": "시간을 확인할게요.",
                    "tool_calls": [tool_call("call_1", "get_current_time", '{"timezone": "UTC"}')],
                },
                "tool_calls",
            ),
            gpt({"content": "지금은 UTC 기준 오후입니다."}, "stop"),
        ]
    )
    result = Agent(llm=llm, tools=TOOLS, system="sys").run("지금 몇 시야?")

    assert result.output == "지금은 UTC 기준 오후입니다."
    assert result.turns == 2 and result.stop_reason == "end"
    assert result.tool_traces[0].name == "get_current_time" and not result.tool_traces[0].is_error
    # 두 번째 요청: system, user, assistant(도구 호출), tool(결과)
    first, second = calls
    assert first["model"] == "gpt-6-luna" and first["max_completion_tokens"] == 1000
    assert first["reasoning_effort"] == "none"
    assert first["tools"][0]["function"]["parameters"]["type"] == "object"
    msgs = second["messages"]
    assert msgs[0] == {"role": "system", "content": "sys"}
    assert msgs[2]["tool_calls"][0]["function"]["name"] == "get_current_time"
    assert msgs[3] == {
        "role": "tool",
        "tool_call_id": "call_1",
        "content": result.tool_traces[0].result,
    }


def test_bad_tool_args_return_error_to_model():
    llm, _ = fake_llm(
        [
            gpt(
                {"content": None, "tool_calls": [tool_call("c", "get_current_time", '{"tz": 1}')]},
                "tool_calls",
            ),
            gpt({"content": "완료"}, "stop"),
        ]
    )
    result = Agent(llm=llm, tools=TOOLS).run("몇 시야?")
    # 잘못된 인자는 예외 대신 에러 결과로 모델에게 돌려줌
    assert result.output == "완료" and result.tool_traces[0].is_error


def test_refusal():
    llm, _ = fake_llm([gpt({"content": None, "refusal": "도와드릴 수 없습니다."}, "stop")])
    result = Agent(llm=llm, tools=TOOLS).run("...")
    assert result.stop_reason == "refusal" and result.output == "도와드릴 수 없습니다."


def test_max_turns():
    loop = gpt({"content": None, "tool_calls": [tool_call("c", "get_current_time")]}, "tool_calls")
    llm, _ = fake_llm(loop)
    result = Agent(llm=llm, tools=TOOLS, max_turns=3).run("hi")
    assert result.stop_reason == "max_turns" and len(result.tool_traces) == 3


def test_client_constructed_from_settings(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    llm = OpenAIClient(api_key="x")
    assert isinstance(llm.client, openai.OpenAI)
    assert llm.model == "gpt-6-luna" and llm.max_tokens == 16000
    assert Agent("gpt-5.4", tools=[]).llm.model == "gpt-5.4"


def test_length_does_not_run_truncated_tool():
    truncated = gpt(
        {"content": None, "tool_calls": [tool_call("call_1", "get_current_time", '{"timez')]},
        "length",
    )
    llm, _ = fake_llm([truncated])
    result = Agent(llm=llm, tools=TOOLS).run("hi")

    assert result.stop_reason == "max_tokens" and result.turns == 1
    assert result.tool_traces == []  # 잘린 도구는 실행하지 않음
    # 결과 없는 도구 호출이 남지 않도록 에러 결과가 붙어 있어야 다음 요청이 유효함
    last = result.messages[-1]
    assert last.role == "tool" and last.tool_call_id == "call_1" and last.is_error


def test_stop_with_tool_calls_is_tool_use():
    # tool_choice 강제 지정 시 finish_reason 이 "stop" 이어도 도구 호출로 처리
    llm, _ = fake_llm(
        [
            gpt({"content": None, "tool_calls": [tool_call("c", "get_current_time")]}, "stop"),
            gpt({"content": "끝"}, "stop"),
        ]
    )
    result = Agent(llm=llm, tools=TOOLS).run("hi")
    assert result.output == "끝" and len(result.tool_traces) == 1
