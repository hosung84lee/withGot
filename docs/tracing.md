# 실행 추적 (Trace)

agent와 workflow가 실행되면서 무엇을 했는지 단계별로 기록합니다.
결과가 이상하거나 에러가 났을 때 **어디서, 무엇을 받아서, 무엇을 했는지** 찾기 위한 기능입니다.
기록은 로컬 SQLite(`src/data/db/app.db`)에 저장되고 외부로 전송되지 않습니다.

## 1. 디버깅 순서

1. 앱의 **Trace** 화면을 엽니다. Agent나 Workflow 결과 아래의 **🔍 Trace 보기**를 눌러도 됩니다.
2. 목록에서 🔴(에러)나 🟡(경고)인 실행을 고릅니다. 사이드바에서 상태로 거르거나 에러 메시지로 검색할 수 있습니다.
3. 맨 위의 **에러 발생 지점** 박스를 봅니다. 에러가 처음 난 단계와 traceback이 나옵니다.
4. **타임라인**에서 그 직전 단계들을 펼쳐 봅니다.

| 증상 | 확인할 곳 |
|---|---|
| API 에러 (400 등) | 에러 난 💬 LLM 단계 → **보낸 요청 (원문)** 탭. 메시지 형식이 맞는지 확인 |
| 엉뚱한 도구를 부름 / 도구를 안 부름 | 💬 LLM 단계 → **응답** 탭의 **추론 요약** (Claude). 왜 그렇게 판단했는지 나옴 |
| 도구 결과가 이상함 | 🛠️ 도구 단계의 **인자**와 **결과**. 인자가 잘못 들어왔는지, 도구가 잘못 처리했는지 구분 |
| 도구 내부 에러 | 🛠️ 도구 단계의 traceback (LLM에게는 에러 메시지만 전달되고, traceback은 trace에만 남음) |
| 답변이 중간에 끊김 | 🟡 경고. `stop_reason`이 `max_tokens`이면 `AGENT_MAX_TOKENS` 늘리기 |
| 끝나지 않음 | 🟡 `max_turns`. 같은 도구를 반복 호출하고 있지 않은지 타임라인 확인 |
| ⏳ 실행 중으로 남아 있음 | 실행 도중 앱이 죽은 것. 마지막으로 기록된 단계가 멈춘 위치 |

다른 사람에게 보여줘야 하면 **trace JSON 내려받기**로 파일을 공유하거나, 주소창의 URL(`?trace_id=...`)을 그대로 보내면 됩니다.

## 2. 무엇이 기록되나

trace 하나는 실행 1회이고, 그 안에 단계(span)들이 부모-자식 관계로 쌓입니다.

```
🧩 workflow / 🤖 agent      ← trace 루트 (실행 1회)
├─ 💬 llm  turn 1          보낸 요청 원문, 응답, 추론 요약, 도구 호출, stop_reason, 토큰
├─ 🛠️ tool get_current_time 인자, 결과, 에러, traceback
├─ 💬 llm  turn 2
└─ ▶️ step ...              workflow 단계
```

| 종류 | 입력 | 출력 | 속성 |
|---|---|---|---|
| 🤖 agent | 대화 메시지 | 최종 답변 | provider, model, system, tools, stop_reason, turns |
| 💬 llm | **API에 보낸 요청 원문** | 텍스트, 추론 요약, 도구 호출 | turn, stop_reason, usage(토큰), 응답 모델 |
| 🛠️ tool | 인자 | 결과 | tool_call_id, turn |
| 🧩 workflow, ▶️ step | 직접 지정 | 직접 지정 | 직접 지정 |

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

## 3. 기록 원칙

- **시작할 때 먼저 기록**: 단계가 시작되면 바로 `running`으로 저장하고, 끝나면 갱신합니다. 앱이 중간에 죽어도 어디서 멈췄는지 남습니다.
- **요청은 보내기 전에 기록**: API 호출이 실패해도 무엇을 보냈는지 남습니다.
- **traceback은 처음 난 곳에만**: 예외가 상위 단계로 올라가면, 상위 단계에는 `error_origin`(어디서 났는지)만 남깁니다. 같은 traceback이 여러 번 보이지 않습니다.
- **동작을 바꾸지 않음**: 예외는 기록한 뒤 그대로 다시 던집니다.
- **기록 실패가 실행을 막지 않음**: DB 기록이 실패하면 경고 로그만 남기고 agent는 계속 실행됩니다.
- **긴 문자열은 잘라서 저장**: `TRACE_MAX_STR`(기본 20,000자)보다 긴 값은 잘리고 `[잘림: 총 N자]`가 붙습니다.

## 4. 코드에서 쓰기

agent와 mock workflow에는 이미 붙어 있습니다. 새 workflow나 단계를 추적하려면 `span()`으로 감싸면 됩니다.
안에서 실행되는 agent는 자동으로 하위 단계로 들어갑니다.

```python
from backend.tracing import span
from agent import Agent

def run_report_workflow(doc_id: int) -> str:
    with span("workflow", "report", input={"doc_id": doc_id}) as wf:
        with span("step", "문서 불러오기") as s:
            text = load(doc_id)
            s.set(output=text[:200], chars=len(text))     # 출력과 속성 기록

        analysis = Agent("anthropic", name="analyzer").run(f"분석해줘: {text}")
        report = Agent("openai", name="writer").run(f"보고서로: {analysis.output}")

        wf.set(output=report.output)
        return report.output
```

- `s.set(output=..., status="warning", **속성)`: 결과, 상태, 속성을 기록합니다. `status`를 생략하면 정상 종료 시 `ok`입니다.
- `s.set_error(종류, 메시지, traceback)`: 예외 없이 실패를 기록합니다.
- `Agent(name=...)`: trace에 표시될 이름입니다. agent가 여러 개면 구분하기 쉽게 지정하세요.
- `result.trace_id` / `agent.last_trace_id`: 실행의 trace ID. 실패해서 결과가 없을 때는 `last_trace_id`를 씁니다.

조회 함수(`backend/tracing.py`):

```python
from backend.tracing import list_traces, get_trace

for t in list_traces(limit=20):          # 최근 실행 목록 (집계 포함)
    print(t.worst_status, t.name, t.errors, t.input_tokens)

spans = get_trace(trace_id)              # 한 실행의 모든 단계 (시작 순서)
```

## 5. 설정

```env
TRACING_ENABLED=true                     # false 면 기록하지 않음
TRACE_MAX_STR=20000                      # 저장할 문자열 최대 길이
ANTHROPIC_THINKING_DISPLAY=summarized    # Claude 추론 요약 기록 (omitted 면 기록 안 함)
```

Claude는 추론 요약을 받아도 비용이 늘지 않습니다. 추론은 원래 하고 있고, 보여줄지만 정하는 설정입니다.
OpenAI는 Chat Completions API에서 추론 내용을 주지 않아서 추론 요약이 비어 있습니다.

## 6. 관리

- 오래된 기록은 Trace 화면 사이드바의 **관리 → trace 전체 삭제**로 지웁니다.
- 테스트는 테스트마다 임시 DB를 사용하므로(`tests/conftest.py`) 앱 기록에 섞이지 않습니다.
- 저장 위치: `spans` 테이블 (`src/backend/db.py`). 다른 SQLite 도구로 직접 열어봐도 됩니다.
