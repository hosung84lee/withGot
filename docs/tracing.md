# 실행 추적 (Trace)

agent와 workflow가 실행되면서 무엇을 했는지 단계별로 기록합니다.
결과가 이상하거나 에러가 났을 때 **어디서, 무엇을 받아서, 무엇을 했는지** 찾기 위한 기능입니다.
기록은 로컬 SQLite(`src/data/db/app.db`)에 저장되고 외부로 전송되지 않습니다.

## 1. 디버깅 순서

1. 앱의 **Trace** 화면을 엽니다. Agent나 Workflow 결과 아래의 **🔍 Trace 보기**를 눌러도 됩니다.
2. **워크플로우** 목록에서 🔴(에러)나 🟡(경고)인 실행을 고릅니다. 목록 위에서 검색하고 걸러낼 수 있습니다.
   - **검색**: workflow ID, 이름, 입력, 채팅 메시지, 응답 내용, 에러 메시지에서 부분 일치로 찾습니다.
   - **종류**: `chat`, `mock_workflow` 등 워크플로우 이름으로 거릅니다.
   - **상태**: 에러, 경고, 실행 중·중단으로 거릅니다. 하위 단계까지 포함한 가장 나쁜 상태 기준입니다.
   - **페이지**: 최근 활동 순으로 나뉘어 보입니다(페이지당 10~100개). ◀ 이전 / 다음 ▶ 버튼이나 페이지 번호로 이동합니다. 검색 조건을 바꾸면 1페이지로 돌아갑니다.
   - 선택한 워크플로우는 URL에 남아서, 다른 페이지로 넘어가도 아래 상세는 그대로 유지됩니다.
3. 그 아래 **호출(trace)** 목록에서 문제 있는 호출을 고릅니다. 에러 난 호출이 있으면 자동으로 선택됩니다.
4. **에러 발생 지점** 박스를 봅니다. 에러가 처음 난 단계와 traceback이 나옵니다.
5. **타임라인**에서 그 직전 단계들을 펼쳐 봅니다.

| 증상 | 확인할 곳 |
|---|---|
| API 에러 (400 등) | 에러 난 💬 LLM 단계 → **보낸 요청 (원문)** 탭. 메시지 형식이 맞는지 확인 |
| 엉뚱한 도구를 부름 / 도구를 안 부름 | 💬 LLM 단계 → **보낸 요청 (원문)** 탭에서 도구 설명(`tools`)과 시스템 프롬프트 확인. 설명이 모호하면 모델이 잘못 고름 |
| 도구 결과가 이상함 | 🛠️ 도구 단계의 **인자**와 **결과**. 인자가 잘못 들어왔는지, 도구가 잘못 처리했는지 구분 |
| 도구 내부 에러 | 🛠️ 도구 단계의 traceback (LLM에게는 에러 메시지만 전달되고, traceback은 trace에만 남음) |
| 답변이 중간에 끊김 | 🟡 경고. `stop_reason`이 `max_tokens`이면 `AGENT_MAX_TOKENS` 늘리기 |
| 끝나지 않음 | 🟡 `max_turns`. 같은 도구를 반복 호출하고 있지 않은지 타임라인 확인 |
| ⏳ 실행 중으로 남아 있음 | 실행 도중 앱이 죽은 것. 마지막으로 기록된 단계가 멈춘 위치 |

다른 사람에게 보여줘야 하면 **trace JSON 내려받기**로 파일을 공유하거나, 주소창의 URL(`?workflow_id=...&trace_id=...`)을 그대로 보내면 됩니다.

## 2. 무엇이 기록되나

기록은 세 단계로 묶입니다.

```
workflow  chat-20261109-223701-a3f9        ← 워크플로우 실행 1회 / 채팅 대화 1개
├─ trace 4911e47e…  (메시지 1)              ← 호출 1회마다 새 trace_id
│  └─ 🤖 agent
│     └─ 💬 llm turn 1
└─ trace e624143b…  (메시지 2)
   └─ 🤖 agent
      ├─ 💬 llm  turn 1          보낸 요청 원문, 응답, 도구 호출, stop_reason, 토큰
      ├─ 🛠️ tool get_current_time 인자, 결과, 에러, traceback
      └─ 💬 llm  turn 2
```

| | ID 형식 | 단위 | 예 |
|---|---|---|---|
| **workflow** | `{이름}-{YYYYMMDD-HHMMSS}-{난수4}` | 워크플로우 실행 1회, 채팅 대화 1개 | `mock_workflow-20261109-224708-b3fc`, `chat-20261109-224721-8ba4` |
| **trace** | 16자리 무작위 | 호출 1회 (채팅 메시지 1개, 워크플로우 단계 1개, agent 실행 1회) | `4911e47e6552486b` |
| **span** | 16자리 무작위 | 작업 1개 (agent, llm, tool, step) | |

- workflow와 trace는 **1:n**입니다. workflow ID만 보면 어떤 워크플로우인지 알 수 있습니다.
- 채팅은 대화 1개가 workflow 1개입니다. **대화 초기화**를 누르면 새 `chat-...` ID가 생깁니다. Agent 화면 사이드바에 지금 대화 ID가 보입니다.
- mock workflow는 실행 1회가 workflow 1개이고, 단계(입력 파싱, 분석, 결과 생성)마다 trace가 하나씩 생깁니다.
- 워크플로우 없이 코드에서 바로 `Agent().run()`을 하면 agent 이름으로 workflow가 자동으로 만들어집니다(`agent-...`). 모든 trace는 반드시 어떤 workflow에 속합니다.
- 이 구조를 도입하기 전의 기록은 trace마다 `legacy-{trace_id}` workflow로 묶여 있습니다.

| 종류 | 입력 | 출력 | 속성 |
|---|---|---|---|
| 🤖 agent | 대화 메시지 | 최종 답변 | model, system, tools, stop_reason, turns |
| 💬 llm | **API에 보낸 요청 원문** | 텍스트, 도구 호출 | turn, stop_reason, usage(토큰), 응답 모델 |
| 🛠️ tool | 인자 | 결과 | tool_call_id, turn |
| ▶️ step | 직접 지정 | 직접 지정 | 직접 지정 |

모든 단계에 상태, 시작 시각, 소요 시간, 에러(종류, 메시지, traceback)가 함께 기록됩니다.

### 상태

| 아이콘 | 상태 | 의미 |
|---|---|---|
| 🟢 | ok | 정상 |
| 🟡 | warning | 끝났지만 확인 필요 (`max_tokens`, `refusal`, `max_turns`, 잘려서 실행 안 한 도구) |
| 🔴 | error | 예외 발생, 또는 도구가 에러 반환 |
| ⏳ | running | 실행 중. 실행이 끝났는데도 이 상태면 비정상 종료 |
| ⚪ | cancelled | 중단됨 (Streamlit 화면 재실행 등) |

목록의 상태는 **하위 단계까지 포함한 가장 나쁜 상태**입니다. 예를 들어 agent는 정상 종료했어도 중간에 도구 에러가 있었다면 🔴로 표시됩니다.
워크플로우 목록도 같습니다. 채팅에서 메시지 하나라도 에러가 났다면 그 대화는 🔴입니다.

## 3. 기록 원칙

- **시작할 때 먼저 기록**: 단계가 시작되면 바로 `running`으로 저장하고, 끝나면 갱신합니다. 앱이 중간에 죽어도 어디서 멈췄는지 남습니다.
- **요청은 보내기 전에 기록**: API 호출이 실패해도 무엇을 보냈는지 남습니다.
- **traceback은 처음 난 곳에만**: 예외가 상위 단계로 올라가면, 상위 단계에는 `error_origin`(어디서 났는지)만 남깁니다. 같은 traceback이 여러 번 보이지 않습니다.
- **동작을 바꾸지 않음**: 예외는 기록한 뒤 그대로 다시 던집니다.
- **기록 실패가 실행을 막지 않음**: DB 기록이 실패하면 경고 로그만 남기고 agent는 계속 실행됩니다.
- **긴 문자열은 잘라서 저장**: `TRACE_MAX_STR`(기본 20,000자)보다 긴 값은 잘리고 `[잘림: 총 N자]`가 붙습니다.

## 4. 코드에서 쓰기

agent, 채팅, mock workflow에는 이미 붙어 있습니다. 새 워크플로우를 만들 때는 `workflow()`로 감싸고,
안의 단계를 `span()`으로 감싸면 됩니다. 워크플로우 안에서 부모 없이 시작되는 `span()`과 `Agent.run()`은 각각 새 trace가 됩니다.

```python
from agent import Agent
from backend.tracing import span, workflow


def run_report_workflow(doc_id: int) -> str:
    with workflow("report", input={"doc_id": doc_id}) as wf:  # wf.id = report-20261109-...
        with span("step", "문서 불러오기") as s:  # trace 1
            text = load(doc_id)
            s.set(output=text[:200], chars=len(text))  # 출력과 속성 기록

        analysis = Agent(name="analyzer").run(f"분석해줘: {text}")  # trace 2
        report = Agent(name="writer").run(f"보고서로: {analysis.output}")  # trace 3

        wf.set(output=report.output)
        return report.output
```

- `workflow(이름, input=..., workflow_id=None)`: 워크플로우 실행 묶음. ID는 이름으로 자동 생성됩니다.
  같은 `workflow_id`로 여러 번 열면 같은 워크플로우에 trace가 쌓입니다. 채팅이 이 방식입니다(메시지마다 `workflow("chat", workflow_id=대화ID)`).
- `new_workflow_id(이름)`: ID를 미리 만들어 둘 때 씁니다(예: 채팅 화면이 처음 열릴 때).
- `wf.set(output=..., **속성)` / `s.set(output=..., status="warning", **속성)`: 결과, 상태, 속성을 기록합니다. `status`를 생략하면 정상 종료 시 `ok`입니다.
- `s.set_error(종류, 메시지, traceback)`: 예외 없이 실패를 기록합니다.
- 워크플로우 코드에서 span 밖에서 난 예외도 워크플로우에 traceback과 함께 기록됩니다.
- `Agent(name=...)`: trace에 표시될 이름입니다. agent가 여러 개면 구분하기 쉽게 지정하세요.
- `result.trace_id`, `result.workflow_id` / `agent.last_trace_id`, `agent.last_workflow_id`: 실행의 ID입니다. 실패해서 결과가 없을 때는 `last_*`를 씁니다.

조회 함수(`backend/tracing.py`):

```python
from backend.tracing import (
    get_trace,
    get_workflow,
    list_traces,
    list_workflows,
    search_workflows,
)

for w in list_workflows(limit=20):  # 최근 워크플로우 (소속 trace 합산)
    print(w.worst_status, w.id, w.traces, w.errors, w.input_tokens)

# 검색 + 페이지 (화면과 같은 조건)
page = search_workflows(query="환율", statuses=["error"], name="chat", page=1, page_size=20)
print(page.total, page.pages, [w.id for w in page.items])

wf = get_workflow(workflow_id)  # 워크플로우 입력/출력/에러
traces = list_traces(workflow_id)  # 그 워크플로우의 호출들 (시작 순서)
spans = get_trace(trace_id)  # 한 호출의 모든 단계 (시작 순서)
```

## 5. 설정

```env
TRACING_ENABLED=true                     # false 면 기록하지 않음
TRACE_MAX_STR=20000                      # 저장할 문자열 최대 길이
```

## 6. 관리

- 오래된 기록은 Trace 화면 사이드바의 **관리 → trace 전체 삭제**로 지웁니다.
- 테스트는 테스트마다 임시 DB를 사용하므로(`tests/conftest.py`) 앱 기록에 섞이지 않습니다.
- 저장 위치: `workflows`, `spans` 테이블 (`src/backend/db.py`). `spans.workflow_id`로 연결됩니다. 다른 SQLite 도구로 직접 열어봐도 됩니다.
