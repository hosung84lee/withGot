# 신과함께 — 에이전트 작업 규칙

> Claude Code 와 Codex 가 함께 읽는 규칙 파일이다. 규칙은 AGENTS.md 에만 쓰고, CLAUDE.md 는 `@AGENTS.md` 한 줄로 이 파일을 불러온다.
> **작업을 시작하기 전에, 수정할 폴더의 AGENTS.md(예: src/agent/AGENTS.md)를 반드시 먼저 읽을 것.**

## 프로젝트

보험 약관을 AI 로 구조화해 사고보장 데이터로 만들고(흐름 1), 그 데이터로 보험금 심사·계산을 지원하는(흐름 2) 해커톤 프로토타입.

- **흐름 1 — 약관 구조화**: 약관 PDF → 텍스트 → 규칙 기반 구조화(약관·보장종목·조·항·호·별표) → 추출 묶음 → LLM 추출(사고보장 JSON + AI 판단 항목 + escalations) → 근거 검증(코드) → 스키마 갭 분석(코드)
- **흐름 2 — 청구 심사 지원**: 청구정보(시나리오 JSON) → 보장 매칭 → 계산 툴(결정론) → AI 판단 항목은 Agent 에 위임 → 심사자 검토·승인
- 사람의 역할은 "업무 수행자"가 아니라 "AI 결과의 최종 검토·승인자"다. 데이터 구조와 화면이 이 전환을 보여줘야 한다.
- 동작하는 단순한 코드가 우선. 추상화는 최소한으로.
- 추가 목표(시간이 남을 때만): 청구 서류 이미지 → 청구정보 추출, 계산 코드 자동 생성, 개정 전후 비교.

## 스택 (H0 에 확정)

Python 3.12, uv, Streamlit, Pydantic v2, SQLite, pypdf, FastMCP, pytest, 공식 LLM SDK 하나(해커톤에서 받은 키 기준).
LangChain·LangGraph 등 LLM 프레임워크는 쓰지 않는다. **새 패키지는 추가하기 전에 물어볼 것.**

## 디렉터리와 담당

| 경로 | 내용 | 담당 |
|---|---|---|
| `src/schema/` | Pydantic 데이터 계약 (coverage, judgment, escalation, claim, calc) | **공동 · 잠금** |
| `src/app/` | Streamlit UI (main.py + views/) | 앱 |
| `src/backend/` | 설정, DB, 파일 저장 | 앱 |
| `src/workflow/policy/` | 흐름 1 파이프라인, 구조화·근거 검증·갭 분석(코드) | 약관 |
| `src/agent/policy/` | 흐름 1 LLM 호출 (사고보장 추출) | 약관 |
| `src/agent/llm_client.py` | LLM 공통 클라이언트 (캐시·리플레이) | 약관 |
| `src/skills/` | 런타임 Agent 용 스킬 | 약관 |
| `src/workflow/claim/` | 흐름 2 파이프라인 | 보험금 |
| `src/agent/claim/` | 흐름 2 LLM 호출 (AI 판단) | 보험금 |
| `src/mcp_server/` | 보험금 계산 툴 서버 | 보험금 |
| `src/data/pdf/`, `src/data/golden/` | 약관 원본, 정답(약관 JSON = 약관 담당, 계산 시나리오 = 보험금 담당) | **사람만 수정** |
| `src/data/mock/` | 계약 ①~⑤ 예시 (첫날 가짜 데이터) | 앱 |
| `src/data/cache/` | LLM 응답 캐시 (데모용, git 에 커밋) | 약관 |
| `tests/policy/`, `tests/claim/`, `tests/app/` | 영역별 테스트 | 각 영역 |

담당 영역 밖의 파일을 수정해야 하면, **먼저 이유를 말하고 확인을 받을 것.**

## 영역 간 계약

세 영역은 아래 계약으로만 연결된다. 형식은 `docs/TEAM_INTERFACE.md`, 모델은 모두 `src/schema/` 에 있다.

| 계약 | 만드는 쪽 → 쓰는 쪽 | 모델 위치 |
|---|---|---|
| ① 사고보장 JSON (`Product`) | 약관 → 보험금·앱 | `schema/coverage.py` |
| ② AI 판단 항목 정의·결과 | 약관(정의) → 보험금(판단) → 앱 | `schema/judgment.py` |
| ③ escalations (스키마에 없는 항목) | 약관(·보험금) → 앱 | `schema/escalation.py` |
| ④ 청구정보 (시나리오) | 앱 → 보험금 | `schema/claim.py` |
| ⑤ 계산 결과 | 보험금 → 앱 | `schema/calc.py` |
| 화면 ↔ 워크플로 | 워크플로 → 앱 | `workflow/policy/__init__.py`, `workflow/claim/__init__.py` 의 공개 함수 |

## 절대 규칙

1. **`src/schema/` 는 수정하지 말 것.** 변경이 필요하면 제안(모델, 필드, 이유, 영향 범위)만 출력하고 멈출 것. 사람이 셋의 합의 후 직접 고친다.
2. **`src/data/pdf/`, `src/data/golden/` 은 수정하지 말 것.** 테스트가 실패하면 코드를 고칠 것. 기대 결과가 이상해 보이면 `docs/mismatch/<주제>.md` 에 리포트를 남기고 해당 케이스는 건너뛸 것.
3. **추측 금지.** 약관에 표준 스키마로 담을 수 없는 내용이 있으면 그럴듯한 값을 만들지 말고 `escalations` 로 내보낼 것. 제품 동작과 코딩 에이전트 자신 모두에 적용된다.
4. 모든 LLM 호출은 `src/agent/` 를 통해서만 한다. LLM 출력은 반드시 `src/schema/` 모델로 검증한 뒤 사용할 것.
5. **LLM 에게 금액·날짜를 계산시키거나 지급 여부를 정하게 하지 말 것.** 계산은 계산 툴(결정론적 코드)로만 한다. 금액은 int(원), 비율은 `{numerator, denominator}`, 날짜는 `YYYY-MM-DD`.
6. 약관의 규칙 값(기간, 비율, 금액, 한도, 코드 범위)을 코드에 하드코딩하지 말 것. 사고보장 JSON 에서 읽는다.
7. AI 가 만든 결과에는 **결과, 근거, 사용한 소스**가 함께 있어야 한다. 소스(약관·조·항·별표·인용문, 서류 경로)는 실제 입력에 존재하는 것만 쓰고, 근거 검증은 코드로 한다.
8. 앱(`src/app/`)은 워크플로의 공개 함수만 호출한다. 앱에서 LLM 호출, 판정, 금액 계산 금지(표시만).
9. 테스트·샘플 데이터는 가상 데이터만 쓸 것. 실제 개인정보 형태의 데이터를 만들지 말 것.
10. **사내 Confidential 자료(내부 시스템 테이블명·컬럼명·코드값·내부 URL·화면 캡처)를 코드·문서·프롬프트·커밋에 넣지 말 것.** 개념만 일반 이름으로 쓴다.
11. 파일 경로는 `pathlib`, 텍스트 파일은 `encoding="utf-8"` 을 명시할 것 (Windows 환경).

## 작업 방식

1. 구현 전에 계획을 먼저 짧게 보여줄 것.
2. 작업 단위가 끝나면 해당 영역 테스트를 실행할 것. 통과하면 커밋한다.
3. 커밋 메시지: `[app]` / `[policy]` / `[claim]` / `[schema]` 태그 + 한국어 한 줄. 예: `[claim] 실손 통원 공제 계산 추가`
4. 작업 하나 = 커밋 하나. 관련 없는 파일은 같이 고치지 말 것.
5. 리뷰를 요청받으면 코드를 고치지 말고 문제 목록만 낼 것.

## 명령 (Windows, H0 에 확정 후 갱신)

- 의존성: `uv sync`
- import 기준: `src/` 를 루트로 (`from schema.coverage import Product`). pyproject 에 패키지로 등록하거나 `$env:PYTHONPATH="src"`
- 앱: `uv run streamlit run src/app/main.py`
- 테스트 전체: `uv run pytest -q` / 영역별: `uv run pytest -q tests/policy`, `tests/claim`, `tests/app`
- 실제 약관 PDF 테스트(느림): `uv run pytest -q --pdf`
- MCP 서버(stdio): `uv run python -m mcp_server.server`
- 데모 리플레이: `$env:REPLAY="1"` 후 앱 실행 (LLM 캐시만 사용)

## 불일치 리포트 형식 (`docs/mismatch/<주제>.md`)

케이스 / 단계 / 기대값 / 실제값 / 차이 원인 추정 / 관련 약관·스키마 문장 / 사람에게 묻고 싶은 것
