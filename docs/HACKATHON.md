# 해커톤 준비 노트 (새 PC 에서 시작하기)

2026-11-09~11 에 한 작업을 정리한 문서입니다 (최종: 2026-11-11, main `d137655` 이후). 새 PC 에서 이 문서를 보고 환경을 세팅하고,
[REBUILD_GUIDE.md](REBUILD_GUIDE.md) 를 따라 새 저장소에 다시 구현할 수 있게 썼습니다.

> **설계 변경 (11-11): 약관 분석의 목표 = 미리 정의한 보장 JSON 스키마를 약관에서 뽑아내기.**
> 스키마는 [`src/schema/json/coverage.json`](../src/schema/json/coverage.json) (팀 초안 PR #5 를 샘플 약관 7개로 보완),
> 분석·추가 이유·남은 결정은 [coverage_json_schema.md](coverage_json_schema.md), 예시는 `cov_sample.json`(초안 2건)·
> `cov_samples_7policies.json`(7개 약관 12건). 구현 방법은 [REBUILD_GUIDE.md 21장](REBUILD_GUIDE.md).
> 약관 구조화(M1~M5)는 그대로 쓰고, 그 위에서 사고보장 데이터(Product) 대신/함께 이 스키마로 뽑습니다.

> **중요: 해커톤에서는 이 저장소 코드를 쓸 수 없고 새 저장소에 처음부터 다시 만들어야 합니다.**
> 이 저장소는 참고용이고, 다시 만들 때는 [REBUILD_GUIDE.md](REBUILD_GUIDE.md)(설계·규칙·정답 수치·테스트 예시)를 따르세요.

- 저장소: https://github.com/hosung84lee/withGot (브랜치 `main`)
- **3명 분담(약관·보험금·앱)과 영역 간 계약**: [TEAM_INTERFACE.md](TEAM_INTERFACE.md) — H0 에 셋이 함께 확정
- **새 저장소용 에이전트 규칙(AGENTS.md / CLAUDE.md / settings.json)**: [hackathon_templates/](hackathon_templates/)
- 세부 문서: [약관 구조화·검증](terms.md) · [사고보장 데이터 추출](coverage_extract.md) · [사고보장 스키마](coverage_schema.md) · [사고보장 테이블](coverage_tables.md)

## 1. 한눈에 보기

| 단계 | 상태 | 위치 |
|---|---|---|
| PDF 텍스트 추출 | 동작 | `src/terms/extract.py` |
| 약관 구조화 (약관·보장종목·관·조·항·호, 별표·부록) | **동작 · 실제 약관 7개로 검증** | `src/terms/parser.py` |
| 구조 검증 (번호·인용) | **동작 · 7개 약관에서 원문 오류 1건만 남음** | `src/terms/validator.py` |
| AI 조항 분석 (분류·요약·불공정 조항) | 코드 있음 (병렬·부분 실패 허용), **화면에서는 뺌** (설계 변경) | `src/terms/analyzer.py` |
| **보장 JSON 스키마** (coverage.json) + 7개 약관 예시 12건 | **동작 · 스키마 검증 통과** | `src/schema/json/`, `tools/schema_samples/build.py` |
| **약관 → 스키마 AI 추출** (조문 + 지급기준표 별표 → JSON, jsonschema 재시도·부분 살리기·캐시) | 코드·테스트(가짜 LLM) 완료, **실제 LLM 미실행** (크레딧 없음) | `src/coverage_json/extract.py` |
| 사고보장 데이터 → 스키마 변환, **두 약관 스키마 비교** | 동작 (API 없이) | `src/coverage_json/convert.py`, `compare.py` |
| 앱: 약관 분석(파일 올리기 → 구조 뷰어·사고보장·테이블·JSON, 샘플 7개, **약관 비교 탭**) | 동작 | `src/app/views/terms_page.py`, `src/app/compare_view.py` |
| 앱: **보장맵** (진료 서류 → 치료 항목·진단 → 약관 보장 → 근거 조항 그림, 실손 참고 계산) | 동작 · 실손 2605·인터넷암 2404 | `src/coverage_map/`, `src/app/views/coverage_map_page.py` |
| 사고보장 스키마 (정액 + **실손**) | 동작 | `src/schema/coverage.py` |
| 사고보장 추출: 묶음 → LLM → 근거 검증 → 정답 비교 | **코드·테스트 완료, 실제 LLM 미실행** | `src/coverage_extract/` |
| 정액형 근거 검증 (별표) + 암진단 정답 초안 | 동작 · 인터넷암보험 근거 8/8 (초안, 확인 필요) | `src/coverage_extract/grounding.py`, `tests/fixtures/cancer_2404_diagnosis_draft.json` |
| 스키마 갭 분석 (원문에 있는데 데이터로 못 담은 것 → 확장 제안) | 동작 · 실손 2605 에서 16종, 인터넷암 2404 에서 10종 · 약관 분석 화면 '스키마 갭' 탭 | `src/coverage_extract/gaps.py` |
| 사고보장 데이터 ↔ 테이블(SQLite) 저장·조회 | 동작 · 저장 후 읽으면 원래 데이터와 같음 | `src/coverage_store/` |
| 약관 구조화 뷰어 (HTML) | 동작 | `tools/terms_viewer/` |

위 표는 **이 저장소(참고용)** 의 상태입니다. 해커톤에서는 새 저장소에 [REBUILD_GUIDE.md](REBUILD_GUIDE.md) 마일스톤 순서로
다시 만들고, M6 에서 처음으로 실제 OpenAI 추출을 돌려 정답과 비교합니다 (5장).

## 2. 새 PC 에서 새 저장소로 시작하기 (Windows)

해커톤에서는 이 저장소를 clone 하지 않고 **새 저장소를 만들어** 처음부터 구현합니다.
PowerShell 기준입니다. 설치 후에는 **터미널을 새로 열어야** `git`, `uv` 명령이 잡힙니다.

### 2.1 도구 설치

```powershell
winget install --id Git.Git -e --source winget
winget install --id astral-sh.uv -e --source winget
# (터미널 새로 열기)

git config --global user.name "hosung84lee"
git config --global user.email "<본인 이메일>"
git config --global core.quotepath false   # 한글 파일명이 \354\202… 처럼 깨지지 않게
```

macOS 라면 `brew install git uv`.

### 2.2 새 저장소 만들기

1. GitHub 웹에서 **New repository** → 이름 정하고 README·.gitignore 없이 빈 저장소로 만듦.
2. 로컬에서 프로젝트를 만들고 연결:

```powershell
cd D:\dev                         # 원하는 작업 폴더
uv init <새저장소이름> --python 3.12
cd <새저장소이름>
uv add pydantic pydantic-settings python-dotenv pypdf openai
uv add --dev pytest ruff

# .gitignore 에 최소한 아래를 넣기
#   .venv/  .env  __pycache__/  .pytest_cache/  .ruff_cache/

git add .
git commit -m "프로젝트 시작"
git branch -M main
git remote add origin https://github.com/<계정>/<새저장소이름>.git
git push -u origin main           # 처음 push 때 브라우저로 GitHub 로그인
```

3. 에이전트 규칙과 폴더 만들기: [hackathon_templates/](hackathon_templates/) 의 파일을 새 저장소 루트에 복사하고
   README 의 명령으로 하위 폴더 `CLAUDE.md` 를 만듭니다. 폴더 구조와 담당은 [TEAM_INTERFACE.md 9장](TEAM_INTERFACE.md).
   복사한 뒤 Claude Code 에서 `src/schema/` 파일 수정을 시켜 보고 **거부되는지** 확인하세요 (잠금 리허설).

4. `.env` 파일 (git 에 넣지 않음):

```ini
OPENAI_API_KEY=sk-...             # 해커톤에서 받은 키
OPENAI_MODEL=gpt-6-luna           # 쓸 모델 이름
```

### 2.3 약관 PDF 준비

[REBUILD_GUIDE.md 2.1](REBUILD_GUIDE.md) 의 약관 7개를 받아 새 저장소의 데이터 폴더(예: `data/policies/`)에 넣습니다.
받는 곳: 이 저장소의 `insurance-workbench/data/reference/policies/` (GitHub 웹에서 파일별 다운로드) 또는 삼성생명 공시실.
최소한 **실손 2605**(`삼성생명_급여실손의료비보장보험_2605갱신형_약관_2026-09-23.pdf`)는 꼭 필요합니다 (정답 데이터 기준).

### 2.4 구현 시작

- H0(첫 1시간): 셋이 [TEAM_INTERFACE.md](TEAM_INTERFACE.md) 11장 체크리스트를 확정하고 `src/schema/` 와 `src/data/mock/` 를 만든 뒤 나눠서 시작합니다.
- 약관 담당은 [REBUILD_GUIDE.md](REBUILD_GUIDE.md) 를 열어 두고 마일스톤 M1 부터 진행합니다.
  (문서 반입이 허용되면 새 저장소 `docs/` 에 복사해 두면 Claude Code 가 읽기 편합니다. 대회 규정을 먼저 확인하세요.)
- Claude Code 첫 요청 예: "REBUILD_GUIDE.md 의 마일스톤 M1 부터 순서대로 구현해줘. 각 완료 기준을 테스트로 만들고 통과하면 다음으로 넘어가."
- 실제 PDF 테스트는 느리므로(약관 하나 25~35초) 처음부터 `pytest --pdf` 같은 옵션으로 분리해 두세요.

## 3. (참고) 이 저장소를 그대로 실행해 보기

해커톤 PC 가 아닌 곳에서 지금 만든 결과를 확인할 때만 씁니다.

```powershell
git clone https://github.com/hosung84lee/withGot
cd withGot
uv sync
copy .env.example .env            # OPENAI_API_KEY 입력
```

```powershell
# 빠른 테스트 (약 5초, 170개 통과 · 9개 건너뜀이 정상)
uv run pytest

# 실제 약관 PDF 테스트까지 (약 4분, 전부 통과가 정상)
uv run pytest --pdf

# 7개 약관 스키마 예시 다시 만들고 검증
uv run python tools/schema_samples/build.py

# 사고보장 추출 묶음 보기 (API 키 없이)
uv run python -m coverage_extract "insurance-workbench/data/reference/policies/삼성생명_급여실손의료비보장보험_2605갱신형_약관_2026-09-23.pdf" --dry-run

# 정답 파일 근거 확인 (API 키 없이) → "근거 확인 11건 · 검토 필요 0건"
uv run python -m coverage_extract "insurance-workbench/data/reference/policies/삼성생명_급여실손의료비보장보험_2605갱신형_약관_2026-09-23.pdf" --ground tests/fixtures/silson_2605_disease_covered.json

# 앱 실행
uv run streamlit run src/app/main.py
```

PowerShell 에서 한글 출력이 깨지면 먼저 `$env:PYTHONIOENCODING="utf-8"` 를 실행하세요.

## 4. 데이터 (약관 PDF)

| 위치 | 내용 | git |
|---|---|---|
| `insurance-workbench/data/reference/policies/` | 삼성생명 약관 7개 (실손 2601·2605, 암보험 3종, 특약 2개). 파일명 `회사_상품명_종류_기준일.pdf` | **포함** |
| `insurance-workbench/data/reference/*.pdf` | 한화 H종신, 라이나 암보험 등 | 제외 (`.gitignore`). 출처 URL 은 `data/reference/sources.json` |
| `insurance-workbench/data/synthetic/` | 가상 진료비 영수증·진단서 | 포함 |

`insurance-workbench/` 는 별도 프로젝트(FastAPI + React)입니다. 자체 세팅은
`insurance-workbench/LOCAL_SETUP.md`, 테스트는 그 폴더에서 `uv run pytest` (23개).
withGot 최상위 `pytest` 는 `tests/` 만 봅니다.

## 5. 해커톤에서 할 일 (역할별)

공통 (H0, 셋이 함께): 새 저장소 세팅(2장) → [TEAM_INTERFACE.md](TEAM_INTERFACE.md) 11장 체크리스트 확정 → `src/schema/` 작성·잠금 →
`src/data/mock/` 에 예시(①~⑤) 넣기. 통합 시점은 **1일차 저녁**(실제 추출 → 계산 → 화면 한 줄)과 **2일차 점심**(정답 일치율 측정).

**약관** — [REBUILD_GUIDE.md](REBUILD_GUIDE.md)

0. **(설계 변경)** 최종 산출물은 보장 JSON 스키마(coverage.json) 목록. H0 에 [coverage_json_schema.md 3장](coverage_json_schema.md)의
   열린 결정(보장 단위 묶기/나누기 등)을 셋이 정하고 스키마를 잠근 뒤, 아래 순서는 그대로 하되 M6 부터는 가이드 21장대로 스키마로 뽑습니다.
1. **M1~M5 재구현** (API 키 없이). 마일스톤마다 가이드 16장 예시와 15장 수치로 확인. 정답은 가이드 13장·20장.
2. **M6 첫 실제 추출** — 실손 2605 주계약 《질병급여형》 묶음 하나(약 7,700자) → 근거 검증 + 정답 비교(일치율). 1일차 저녁 통합 전에.
3. **프롬프트 다듬기** — 비교의 `값이 다름`·`빠짐`, 근거 검증의 `NUMBER_NOT_FOUND` 를 보고 고침. 스키마에 없는 항목은 escalations 로.
4. **M9 정액형** — 별표 근거 + 암진단 묶음(별표·정의 조, 가이드 20장 3~5번) → 인터넷암보험 실제 추출. 보험금 담당의 정액 계산과 맞춤.
5. **M7 갭 분석** — 발표 차별점. 실손 16종 + 정액형 10종(병기 기준, 묶음 단위 1회, 성별, 재발 등).
6. (시간이 남으면) 실손 8묶음 전체, M8 테이블 저장, 개정 비교(2601 ↔ 2605).

**보험금** — [TEAM_INTERFACE.md](TEAM_INTERFACE.md) ②④⑤·7장

1. `calc_actual_cost` (실손: 공제 max·보상률·회당/연간 한도·자기부담 상한) — mock ①(실손 정답)로, 7장 S101~S103 통과.
2. `calc_fixed_rate` (정액: 보장개시일 90일·1년 이내 50%·최초 1회·Ⅰ+Ⅱ+Ⅲ 합산) — 암 정답 초안으로, S001~S006 통과.
3. 보장 매칭(KCD → 담보코드, 사건 유형 → 위험률), AI 판단 위임(병기·조직형 등 `unknown` → 검토).
4. 계산 정답 데이터 30건 확정 (실손 10, 정액 20) — 경계 케이스: 면책 만료 전날/당일, 1년 이내 마지막 날, 재발, 유사암.

**앱** — [TEAM_INTERFACE.md](TEAM_INTERFACE.md) 1·8장, [hackathon_templates/src/app/AGENTS.md](hackathon_templates/src/app/AGENTS.md)

1. mock 으로 화면 4개 뼈대: 약관 구조화(진행 표시) / 사고보장 데이터·근거·갭 검토 / 시나리오 입력·계산 결과 / 검토·승인.
2. 근거 원문을 나란히 보여주기 — 참고: 이 저장소의 `tools/terms_viewer/` 와 사고보장 시각화 페이지(규칙 → 조·항·별표 원문 하이라이트).
3. 1일차 저녁부터 mock 을 공개 함수(`run_policy`, `run_claim`) 호출로 교체. 발표 시연 흐름과 대본.

## 6. 한 작업 (커밋 순서)

### 2026-11-11

| 커밋 | 내용 |
|---|---|
| `d137655` | **보장 JSON 스키마 보완(샘플 약관 7개 분석)** + 7개 약관 예시 12건 + `src/coverage_json/`(검증·KCD 정규식·변환·AI 스키마 추출·비교) + 약관 분석 「약관 비교 (스키마)」 탭 + [coverage_json_schema.md](coverage_json_schema.md) |
| `650f15d` | 보장맵: 진단서 질병코드 → 정액형 진단 보장(인터넷암 2404 정답 초안), 별표 근거 원문 |
| `2fc4032` | (팀원 PR #5) 보장 JSON 스키마 초안 `coverage.json` + 예시 `cov_sample.json` |
| `45a5d8c`·`589820e`·`a00b371` | 보장맵 보장종목 기본값·비급여 판정, 사고보장 추출 형식 오류 항목만 빼고 살리기, 보장맵에 실제 약관 PDF 연결·약관 분석을 사고보장 추출로 전환·큰 약관(200쪽+) 병렬 처리 |
| `5e51ad8` | 약관 분석 화면(파일 올리기 첫 탭, 구조 뷰어) + 보장맵 첫 버전 |
| `338ec2e` | 재구현 가이드: 리허설(M1~M2 새로 구현)·LLM 시험(일치율 82%) 결과 반영 |

### 2026-11-10

| 커밋 | 내용 |
|---|---|
| `0e61179` | 사고보장 데이터 ↔ 테이블(SQLite) 13개 저장·조회 (`src/coverage_store/`, [coverage_tables.md](coverage_tables.md)) |
| `29fc5e3` | 스키마 갭 분석 (`coverage_extract/gaps.py`): 원문에 있는데 데이터로 못 담은 개념 16종 + 근거 없는 원문의 이유 3가지 |
| `20403d3` | 정액형 근거 검증(별표, 약관 범위·번호 정확히) + 인터넷암보험 암진단 정답 초안(근거 8/8) |
| (이 커밋) | 팀 인터페이스 명세, 에이전트 규칙 템플릿, 재구현 가이드 M7~M9, 이 문서 역할별 할 일 |

### 2026-11-09

저장소 정리

- `insurance-workbench` 프로젝트와 약관 PDF 를 저장소에 추가, 약관 PDF 이름을 `회사_상품명_종류_기준일` 로 통일
- 이전 브랜치(`feature/custom-agent`, `claude/terms-analysis-structure-validation-sqosfl`)를 main 에 머지하고 삭제
- 최상위 `pytest` 가 `insurance-workbench` 테스트를 수집하지 않게 `testpaths = ["tests"]`
- (팀원 PR #4) 앱을 **OpenAI 전용**으로 전환, workflow-id 기반 추적, Trace 목록 검색. 사고보장 추출도 이 구조(`Agent(model, llm=…)`)에 맞춤

약관 구조화 (`src/terms/`) — 실제 약관 PDF 에서 찾은 문제를 하나씩 고침

| 커밋 | 내용 |
|---|---|
| `0bb15ad` | 목차 줄(쪽 번호) 건너뛰기, 두 줄 괄호 제목, 주계약+특약 묶음을 약관(part)별로 분리, 별표 뒤 본문 복귀, 부록(인용 법령) 보관 |
| `c111ef4` | 인용 추출: `제8조(제목) 제4항`, `제1항부터 제7항`, 줄을 넘는 법령 이름·반각 `｢｣`, 줄 맨 앞 인용을 조로 읽지 않기 |
| `4a3c727` | 편-조 번호 `제2-14조`, 공통 `[특약 약관] 제1편 일반사항` |
| `bccbfba` | 줄바꿈된 `…합니`/`다.` 를 목 번호로 읽지 않기, 괄호 없는 `별표1 …` |
| `965b942` | 보장종목 구분 `《질병급여형》` (보장종목마다 같은 번호의 조) |
| `00133e5` | 옆 안내 상자(`용어 해설`, `설명 <…>`, `유의사항`) 번호를 본문 번호로 읽지 않기, 번호 없는 `별표 …` |
| `e4ca53e` | 표 아래 각주 `㈜ 1. …`, 상자가 낀 조 제목 인용 |
| `9de58d4` | 실제 PDF 테스트를 `pytest --pdf` 옵션으로 분리 |

실손 2605 기준 결과 (수정 전 `16a4211` → 지금)

| | 수정 전 | 지금 |
|---|---|---|
| 찾은 조 | 77 (전부 목차 줄) | 173 |
| 조로 분류된 원문 | 11% | 59% (나머지 대부분 부록 법령·목차) |
| 검증 오류 / 경고 | 14 / 65 | 0 / 0 |

7개 약관 전체에서 남은 검증 문제는 **인터넷암보험 고액치료비암진단특약Ⅱ의 `제2조의9` 중복 1건**뿐이고,
이건 원문 오타로 보입니다 (같은 PDF 의 다른 약관은 AJCC 조항을 `제2조의10` 으로 씀).

사고보장 데이터 (이번 작업, 아래 7장)

## 7. 사고보장 추출 요약

자세한 내용은 [coverage_extract.md](coverage_extract.md).

- **스키마 확장** (`src/schema/coverage.py`): 실손 표현 — 급여·비급여(`cost_type`), 보상률, 공제금액
  (`Deductible`: 정액·비율·본인부담률 중 큰 금액), 금액 한도(`AmountLimit`: 회당·연간 …), 자기부담 연간 상한,
  계약 종료 후 연장 보상(`Extension`), 보상 제외(`Exclusion`), 보장종목(`section`), 추가 근거(`extra_sources`).
- **묶음** (`bundles.py`): 실손 2605 → 8묶음, 제도성 특약 제외.
- **추출** (`extractor.py`): OpenAI (`agent.Agent`), JSON 재시도, id 재지정.
- **근거 검증** (`grounding.py`): 인용문·숫자를 원문과 대조.
- **정답 비교** (`compare.py`) + 정답 파일 `tests/fixtures/silson_2605_disease_covered.json` (규칙 4 + 제외 7).
- **명령**: `python -m coverage_extract` (`--dry-run`, `--ground`, `--section`, `--out`, `--compare`).

## 8. 약관 구조화 뷰어

약관 7개를 지금 코드로 구조화·검증한 결과를 HTML 한 장으로 만듭니다
(원문 분류 지도, 약관·보장종목별 트리, 조문 상세, 인용 관계, 검증 결과, 수정 전과 비교).

```powershell
uv run python tools/terms_viewer/build.py
start tools/terms_viewer/out/terms-viewer.html     # 브라우저로 열기 (macOS: open …)
```

- 결과 파일(`tools/terms_viewer/out/`)은 git 에 넣지 않습니다. 약 3MB, PDF 추출 때문에 1~2분 걸림.
- '수정 전과 비교' 기준 수치는 `tools/terms_viewer/baseline_16a4211.json`.
- 오늘 claude.ai 에 올린 같은 페이지(비공개 Artifact)가 있지만, 새 PC·다른 계정에서는 이 명령으로 다시 만드세요.

## 9. 알려진 한계

- 사고보장 추출은 실손 2605 에서 6/8 묶음만 실제 LLM 으로 돌려 봄 (11-10). **스키마 직접 추출은 실제 LLM 미실행** (테스트는 가짜 응답). OpenAI 키는 크레딧이 있어야 함 (`429 no credits` 면 결제 페이지에서 충전).
- 화면 테스트 PC(켜진 지 91일)에서 Windows 의 오래 켠 PC 문제(TIME_WAIT 가 안 사라져 포트 고갈)로 화면이 가끔 멈추거나 빈 화면이 됨 → **재부팅으로 해결**. 앱 문제 아님.
- 암진단 정답은 **초안** (팀원 원문 대조 필요). 정액형 묶음은 별표(지급기준표·분류표)·정의 조까지 넣음 — 사람이 쓴 응답으로 추출 경로를 돌리면 초안과 100% 일치하지만 실제 LLM 은 미실행.
- 갭 분석이 제안한 스키마 확장 26종(실손 16 + 정액형 10)은 아직 반영 안 됨 (해커톤 H0 에서 넣을 것 고르기: 추천 합산 한도·1회 산정 규칙).
- 옆 안내 상자는 끝 표시가 없어 번호로 끝을 판단합니다. 상자 안 다음 번호와 본문 다음 번호가 같으면(상자 ①② 뒤 본문 ③) 구분 못 함. 실제 약관 7개에서는 문제 없었음.
- 번호 없는 각주 `(주)` 바로 뒤에 본문 `1.` 이 오면 각주 목록으로 볼 수 있음.
- 보장종목 구분은 끝 표시가 없어 다음 관에서 끝난 것으로 봅니다 (공통인 제4조의2 가 앞 보장종목에 붙음, 검증에는 영향 없음).
- AI 분석·사고보장의 조 표기는 `제3조` 처럼 표기만 써서, 특약이 여러 개면 어느 약관의 조인지 `part`/`section` 과 함께 봐야 합니다.

## 10. Claude Code / Codex 로 작업할 때

- 새 PC 의 Claude Code 는 이전 대화·메모리를 모릅니다. 규칙은 [hackathon_templates/](hackathon_templates/) 를 복사한 AGENTS.md(+ CLAUDE.md `@AGENTS.md`)가 알려주고,
  할 일은 아래처럼 프롬프트로 줍니다.
- 역할별 첫 요청 예:
  - **약관**: "docs/REBUILD_GUIDE.md 의 마일스톤 M1 부터 순서대로 구현해줘. 각 완료 기준을 테스트로 만들고 통과하면 다음으로 넘어가. 코드는 src/workflow/policy/ 에."
  - **보험금**: "docs/TEAM_INTERFACE.md 의 ①④⑤ 계약과 7장 시나리오로 src/mcp_server/ 에 calc_actual_cost 를 만들어줘. 입력은 src/data/mock/ 의 실손 JSON, S101~S103 을 테스트로."
  - **앱**: "docs/TEAM_INTERFACE.md 1·8장과 src/app/AGENTS.md 를 읽고 src/data/mock/ 의 예시로 화면 4개 뼈대를 만들어줘. 워크플로는 아직 호출하지 말고 mock 만."
- 구조화 규칙을 고쳤으면 실제 약관 PDF 테스트까지 돌려 15장 수치가 그대로인지 확인하세요.
