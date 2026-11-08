"""에이전트가 호출할 수 있는 도구(skill) 등록소.

함수에 @tool 을 붙이면 타입 힌트로 JSON Schema 를 만들고 등록합니다.
"""

import inspect
import json
import traceback
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError, create_model

from schema.agent import Attachment, ToolOutput, ToolSpec


class Tool:
    def __init__(self, fn: Callable[..., Any]):
        self.fn = fn
        self.name = fn.__name__
        self.description = inspect.getdoc(fn) or self.name
        fields = {
            name: (
                p.annotation if p.annotation is not inspect.Parameter.empty else str,
                p.default if p.default is not inspect.Parameter.empty else ...,
            )
            for name, p in inspect.signature(fn).parameters.items()
        }
        self.args_model: type[BaseModel] = create_model(
            f"{self.name}_args", __config__=ConfigDict(extra="forbid"), **fields
        )

    @property
    def spec(self) -> ToolSpec:
        schema = self.args_model.model_json_schema()
        schema.pop("title", None)
        for prop in schema.get("properties", {}).values():
            prop.pop("title", None)
        return ToolSpec(name=self.name, description=self.description, parameters=schema)

    def run(self, arguments: dict[str, Any]) -> ToolOutput:
        args = self.args_model.model_validate(arguments)
        result = self.fn(**args.model_dump())
        if isinstance(result, ToolOutput):
            return result
        if isinstance(result, Attachment):  # 파일 하나만 돌려주는 도구
            return ToolOutput(text=f"[첨부: {result.filename}]", attachments=[result])
        if isinstance(result, str):
            return ToolOutput(text=result)
        return ToolOutput(text=json.dumps(result, ensure_ascii=False, default=str))


_REGISTRY: dict[str, Tool] = {}


def tool(fn: Callable[..., Any]) -> Callable[..., Any]:
    _REGISTRY[fn.__name__] = Tool(fn)
    return fn


def get_tools(names: list[str] | None = None) -> list[Tool]:
    if names is None:
        return list(_REGISTRY.values())
    return [_REGISTRY[n] for n in names]


class ToolExecution(BaseModel):
    result: str  # 모델에게 돌려줄 문자열 (에러면 에러 메시지)
    attachments: list[Attachment] = []  # 모델에게 같이 보낼 파일
    is_error: bool = False
    # 아래는 trace 기록용. 모델에게는 보내지 않음
    error_type: str | None = None
    error_message: str | None = None
    traceback: str | None = None


def execute_tool(tools: dict[str, Tool], name: str, arguments: dict[str, Any]) -> ToolExecution:
    """도구 실행. 에러도 예외 대신 결과로 돌려줘서 모델이 스스로 고치게 합니다."""
    t = tools.get(name)
    if t is None:
        return ToolExecution(
            result=f"Error: unknown tool '{name}'",
            is_error=True,
            error_type="UnknownTool",
            error_message=f"unknown tool '{name}'",
        )
    try:
        out = t.run(arguments)
        return ToolExecution(result=out.text, attachments=out.attachments)
    except ValidationError as e:
        return ToolExecution(
            result=f"Error: invalid arguments: {e}",
            is_error=True,
            error_type="ValidationError",
            error_message=str(e),
        )
    except Exception as e:  # noqa: BLE001  도구 내부 오류를 모델에게 전달
        return ToolExecution(
            result=f"Error: {type(e).__name__}: {e}",
            is_error=True,
            error_type=type(e).__name__,
            error_message=str(e),
            traceback=traceback.format_exc(),
        )
