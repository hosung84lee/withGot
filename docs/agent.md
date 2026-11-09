# Agent 사용법

OpenAI(Chat Completions API)를 쓰는 custom agent입니다.
LLM이 필요하면 도구(skill)를 호출하고, 그 결과를 보고 다시 판단하는 과정을 답이 나올 때까지 반복합니다.
실행 과정은 자동으로 기록되어 **Trace** 화면에서 볼 수 있습니다 ([tracing.md](tracing.md)).

## 1. 설정

`.env`에 OpenAI 키를 넣습니다.

```env
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-6-luna   # 토큰 절약용 기본 모델
OPENAI_REASONING_EFFORT=none     # 추론 강도. none 이 토큰을 가장 적게 씀 (gpt-6-luna 는 도구 사용 시 none 필수)

AGENT_MAX_TURNS=10               # LLM 호출 최대 횟수 (무한 루프 방지)
AGENT_MAX_TOKENS=16000           # 응답 1회 최대 토큰
ATTACHMENT_MAX_MB=30             # 첨부 파일 1개 최대 크기
```

모든 설정은 `src/backend/config.py`의 `Settings`에 정의되어 있습니다.

## 2. 사용하기

### 앱에서

```bash
uv run streamlit run src/app/main.py
```

**Agent** 화면에서 대화합니다. 사이드바에서 모델을 바꿀 수 있습니다.
도구가 호출되면 호출 내용과 결과가 함께 표시됩니다.
응답이 잘렸거나(`max_tokens`), 반복 횟수 한도에 걸렸거나(`max_turns`), 거절되면(`refusal`) 경고가 표시됩니다.

### 코드에서

```python
from agent import Agent

result = Agent().run("지금 서울 몇 시야?")  # 모델 생략 시 OPENAI_MODEL 사용

print(result.output)  # 최종 답변
print(result.stop_reason)  # end | max_tokens | refusal | max_turns
print(result.turns)  # LLM 호출 횟수
print(result.tool_traces)  # 호출한 도구, 인자, 결과 목록
print(result.trace_id)  # 이 실행(호출 1회)의 ID
print(result.workflow_id)  # 묶음 ID. 워크플로우 밖에서 실행하면 agent-... 로 자동 생성
```

`stop_reason`으로 결과가 완전한지 확인할 수 있습니다.

| 값 | 의미 | 대응 |
|---|---|---|
| `end` | 정상 종료 | 그대로 사용 |
| `max_tokens` | 응답이 토큰 한도에서 잘림 | `AGENT_MAX_TOKENS`를 늘리기 |
| `max_turns` | 도구 호출을 반복하다 횟수 한도에 걸림 | `AGENT_MAX_TURNS`를 늘리거나 질문을 좁히기 |
| `refusal` | 모델이 요청을 거절함 | 질문 내용 확인 |

옵션:

```python
from skills import get_tools

agent = Agent(
    "gpt-5.5",  # .env 의 기본 모델 대신 사용
    system="너는 문서 관리 비서야. 한국어로 답해.",
    tools=get_tools(["list_uploaded_documents"]),  # 쓸 도구만 골라서 (기본: 전부)
    max_turns=5,
    name="doc-assistant",  # Trace 화면에 표시될 이름
)
```

### 대화 이어가기

`result.messages`에 지금까지의 대화 전체가 들어 있습니다. 여기에 다음 질문을 붙여서 다시 `run()`을 호출합니다.

```python
from schema.agent import AgentMessage

r1 = agent.run("업로드된 문서 몇 개야?")
history = r1.messages + [AgentMessage(role="user", content="그중 PDF만 알려줘")]
r2 = agent.run(history)
```

### 진행 상황 받기

`on_event` 콜백으로 LLM 응답과 도구 실행을 실시간으로 받을 수 있습니다.

```python
def on_event(kind: str, data: dict):
    if kind == "llm":
        print(f"[{data['turn']}턴] {data['stop_reason']}: {data['text']}")
    elif kind == "tool":
        print(f"  도구 {data['name']}({data['arguments']}) → {data['result']}")


agent.run("지금 몇 시야?", on_event=on_event)
```

## 3. PDF·이미지 읽기

agent가 파일을 읽는 방법은 두 가지이고, 둘 다 같은 `Attachment`(첨부 파일)를 씁니다.
지원 형식: PDF, PNG, JPG, GIF, WEBP (파일 1개 최대 `ATTACHMENT_MAX_MB`, 기본 30MB)

| | 1) 메시지에 첨부 | 2) agent가 직접 찾아 읽기 |
|---|---|---|
| 언제 | 사용자가 파일을 올리며 질문할 때 | 보관함에 쌓인 문서 중 agent가 필요한 것을 고를 때 |
| 앱에서 | 채팅 입력창에서 파일 첨부 | 사이드바 **문서 보관함**에 올린 뒤 “3번 문서 요약해줘” |
| 동작 | 파일이 질문과 함께 모델에 전달됨 | `list_uploaded_documents`로 목록 확인 → `read_document(doc_id)`로 열기 |

채팅에 첨부한 파일도 보관함에 저장되므로, 이후 대화에서 agent가 다시 열어볼 수 있습니다.

### 코드에서

```python
from agent import Agent
from backend.attachments import attachment_from_document
from backend.storage import save_upload
from schema.agent import AgentMessage
from schema.document import DocumentKind

doc = save_upload("영수증.jpg", data, DocumentKind.IMAGE)  # 보관함에 저장

# 1) 메시지에 첨부
msg = AgentMessage(
    role="user", content="합계 금액이 얼마야?", attachments=[attachment_from_document(doc)]
)
Agent().run([msg])

# 2) agent가 직접 찾아 읽기 (read_document 도구가 기본 포함)
Agent().run(f"{doc.id}번 문서의 합계 금액 알려줘")
```

### API로 전달되는 방식

| | OpenAI 요청 |
|---|---|
| 메시지 첨부 | user 메시지에 질문 텍스트 + `file`(PDF) / `image_url`(이미지) 파트 |
| 도구 결과 | tool 메시지는 텍스트만 받으므로, 도구 결과 바로 뒤에 파일을 담은 user 메시지를 붙임 |

- 파일 내용은 대화 기록에 저장하지 않고 **경로만** 둡니다. 요청을 만들 때마다 파일을 읽어 base64(data URL)로 넣습니다.
- 대화가 이어지면 같은 파일을 매번 다시 보냅니다.
- trace에는 파일 내용 대신 `<base64 N자 생략>`과 파일명만 기록됩니다.

### 파일을 돌려주는 도구 만들기

도구가 `Attachment`나 `ToolOutput`을 반환하면 모델이 그 파일을 직접 봅니다.

```python
from schema.agent import ToolOutput


@tool
def get_contract_pages(doc_id: int) -> ToolOutput:
    """계약서 원본과 요약 정보를 돌려줍니다."""
    doc = get_document(doc_id)
    return ToolOutput(
        text=f"{doc.filename}, 업로드 {doc.created_at}", attachments=[attachment_from_document(doc)]
    )
```

## 4. 도구 추가하기

`src/skills/`의 파일에 함수를 만들고 `@tool`을 붙이면 됩니다.

```python
# src/skills/builtin.py (또는 새 파일)
from skills.registry import tool


@tool
def search_documents(keyword: str, limit: int = 5) -> list[dict]:
    """파일명에 keyword 가 들어간 문서를 최대 limit 개 찾습니다."""
    ...
```

- **함수 이름**이 도구 이름이 됩니다.
- **docstring**이 도구 설명으로 LLM에 전달됩니다. 언제 쓰는 도구인지 구체적으로 적어야 LLM이 잘 고릅니다.
- **타입 힌트**로 입력 스키마(JSON Schema)가 자동 생성됩니다. 기본값이 없는 인자는 필수 값이 됩니다.
- 반환값이 문자열이 아니면 JSON으로 바꿔서 전달됩니다.
- LLM이 잘못된 인자를 넘기거나 함수에서 예외가 나도 앱은 멈추지 않습니다. 에러 내용을 LLM에게 돌려줘서 스스로 고치게 합니다.

새 파일을 만든 경우 `src/skills/__init__.py`에서 import해야 등록됩니다.

```python
from skills import builtin, my_new_skills  # noqa: F401
```

## 5. 동작 구조 (agent loop)

```
사용자 질문
    │
    ▼
[LLM 호출] ◄──────────────────────────────┐
    │                                     │
    ▼                                     │
stop_reason 확인                          │
    ├─ tool_use   → 도구 실행, 결과 추가 ─┘
    ├─ end        → 최종 답변 반환
    ├─ max_tokens → 잘린 답변 반환 (도구 실행 안 함)
    └─ refusal    → 거절로 종료
```

`src/agent/agent.py`의 `Agent.run()`이 이 루프를 담당합니다.
**계속할지는 응답의 종료 이유(`stop_reason`)로만 판단합니다.**

1. **LLM 호출**: 시스템 프롬프트, 지금까지의 대화, 도구 목록을 OpenAI API로 보냅니다.
2. **응답 기록**: 응답을 대화 기록에 assistant 메시지로 추가합니다.
3. **종료 이유로 분기**
   - `tool_use`: 요청된 도구를 모두 실행하고, 결과를 `role="tool"` 메시지로 대화에 추가한 뒤 1번으로 돌아갑니다.
   - `end`, `max_tokens`, `refusal`: 루프를 끝내고 결과를 반환합니다.
4. `max_turns`에 도달하면 마지막 응답을 반환합니다(`stop_reason="max_turns"`).

**응답이 잘렸을 때(`max_tokens`)**: 도구 인자를 쓰다가 잘렸을 수 있으므로 도구를 실행하지 않습니다.
대신 "실행하지 않음" 에러 결과를 대화에 붙여 둡니다. 결과 없는 도구 호출이 기록에 남으면, 대화를 이어갈 때 API가 에러를 내기 때문입니다.

### 계층 구조

| 계층 | 위치 | 역할 |
|---|---|---|
| Agent | `agent/agent.py` | 루프, 도구 실행, 종료 판단 |
| LLM | `agent/llm.py` (`OpenAIClient`) | 공용 메시지 ↔ OpenAI 요청 형식 변환, LLM 1회 호출 |
| Skills | `skills/` | 도구 등록, 스키마 생성, 실행 및 에러 처리 |
| Schema | `schema/agent.py` | 공용 데이터 모델 (`AgentMessage`, `ToolCall`, `LLMResponse`, `AgentResult`) |

Agent는 공용 형식(`AgentMessage`)만 다루고, OpenAI 요청 형식으로 바꾸는 일은 `OpenAIClient`가 맡습니다.

| 공용 형식 | OpenAI 요청 |
|---|---|
| 시스템 프롬프트 | 첫 메시지 `role: "system"` |
| 도구 정의 | `type: "function"` + `parameters` (JSON Schema) |
| 도구 호출 | `tool_calls` (인자는 JSON 문자열) |
| 도구 결과 (`role="tool"`) | 결과마다 `role: "tool"` 메시지 |

`OpenAIClient`는 `build_request()`(요청 본문 만들기)와 `send()`(보내고 응답 변환)로 나뉘어 있습니다.
요청을 **보내기 전에** trace에 기록하기 위해서입니다. API 에러가 나도 무엇을 보냈는지 남습니다.

### 종료 이유 변환

OpenAI의 `finish_reason`을 공용 값으로 바꿔서 루프에 넘깁니다.

| 공용 값 | OpenAI `finish_reason` |
|---|---|
| `end` | `stop` |
| `tool_use` | `tool_calls`, 또는 `stop`인데 도구 호출이 있을 때 |
| `max_tokens` | `length` |
| `refusal` | `content_filter`, 또는 `message.refusal` 값이 있을 때 |

- `tool_choice`로 특정 함수를 강제 지정하면 도구를 호출해도 `stop`이 올 수 있습니다. 그래서 `stop`인데 도구 호출이 있으면 `tool_use`로 처리합니다. (`length`로 잘린 경우는 그대로 `max_tokens`로 둡니다.)
- 거절되면 `stop_reason="refusal"`로 끝나고, 거절 사유(`message.refusal`)가 답변에 들어갑니다.

### 테스트에서 가짜 LLM 쓰기

`Agent(llm=...)`로 `OpenAIClient`를 직접 넘길 수 있습니다. 테스트는 `tests/fakes.py`의 `fake_llm()`으로 가짜 응답을 돌려주는 클라이언트를 만들어 씁니다.

```python
from fakes import fake_llm, gpt

llm, calls = fake_llm([gpt({"content": "안녕"}, "stop")])
Agent(llm=llm, tools=[]).run("hi")
print(calls[0]["messages"])  # 실제로 보냈을 요청
```

## 6. 테스트

```bash
uv run pytest
```

테스트는 SDK 호출을 가짜 응답으로 바꿔서 API 키 없이 실행되고, 테스트마다 임시 DB를 씁니다.

- `tests/test_agent.py`: 도구 호출 루프, 메시지 형식 변환, 잘못된 인자 처리, 거절 처리, 잘린 응답 처리, `max_turns` 제한
- `tests/test_attachments.py`: 메시지 첨부와 `read_document` 도구, trace의 base64 생략
- `tests/test_tracing.py`: 단계별 기록, API 에러 시 요청과 traceback 보존, 도구 에러, 경고 상태, 기록 실패 시에도 agent 동작

## 7. 현재 한계

- **스트리밍 미지원**: 응답이 끝까지 생성된 뒤에 한 번에 표시됩니다.
- **도구 순차 실행**: LLM이 도구 여러 개를 동시에 요청해도 하나씩 실행합니다.
- **대화 저장 안 함**: 대화 기록은 메모리(Streamlit 세션)에만 있어서, 새로고침하면 사라집니다.
- **긴 대화 관리 없음**: 대화가 길어지면 매번 전체를 다시 보내므로 비용이 늘어납니다.
- **큰 PDF**: 페이지 단위로 나눠 읽는 기능이 없어서, API 크기 제한을 넘는 PDF는 읽지 못합니다.
- **추론 내용 없음**: Chat Completions API는 모델의 추론 내용을 주지 않아서 trace에서 볼 수 없습니다. 판단 근거는 응답 텍스트와 도구 호출로 확인합니다.
