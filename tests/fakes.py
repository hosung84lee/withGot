"""API 키 없이 테스트하기 위한 가짜 OpenAI 응답.

SDK 의 create() 를 바꿔치기해서 실제 네트워크 호출은 하지 않습니다.
"""

from openai.types.chat import ChatCompletion

from agent import OpenAIClient


def gpt(message: dict, finish_reason: str, model: str = "gpt-6-luna") -> ChatCompletion:
    """Chat Completions 응답 1개. message 예: {"content": "안녕"}"""
    return ChatCompletion.model_validate(
        {
            "id": "c1",
            "object": "chat.completion",
            "created": 0,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", **message},
                    "finish_reason": finish_reason,
                }
            ],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
        }
    )


def tool_call(call_id: str, name: str, arguments: str = "{}") -> dict:
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}}


def fake_llm(responses) -> tuple[OpenAIClient, list[dict]]:
    """응답을 차례로 돌려주는 OpenAIClient 와, 보낸 요청 목록.

    responses 는 리스트(차례로 사용) 또는 ChatCompletion 하나(매번 같은 응답).
    Exception 이 들어 있으면 그 차례에 예외를 던집니다.
    """
    llm = OpenAIClient("gpt-6-luna", 1000, api_key="test")
    calls: list[dict] = []
    it = iter(responses) if isinstance(responses, list) else None

    def create(**kwargs):
        calls.append(kwargs)
        r = next(it) if it else responses
        if isinstance(r, Exception):
            raise r
        return r

    llm.client.chat.completions.create = create
    return llm, calls
