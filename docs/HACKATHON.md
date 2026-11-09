# 해커톤 준비 노트 (새 PC 에서 시작하기)

2026-11-09 에 한 작업을 정리한 문서입니다. 새 PC 에서 이 문서만 보고 환경을 세팅하고,
지금까지 만든 기능을 다시 돌려 볼 수 있게 썼습니다.

- 저장소: https://github.com/hosung84lee/withGot (브랜치 `main`)
- 세부 문서: [약관 구조화·검증](terms.md) · [사고보장 데이터 추출](coverage_extract.md) · [사고보장 스키마](coverage_schema.md)

## 1. 한눈에 보기

| 단계 | 상태 | 위치 |
|---|---|---|
| PDF 텍스트 추출 | 동작 | `src/terms/extract.py` |
| 약관 구조화 (약관·보장종목·관·조·항·호, 별표·부록) | **동작 · 실제 약관 7개로 검증** | `src/terms/parser.py` |
| 구조 검증 (번호·인용) | **동작 · 7개 약관에서 원문 오류 1건만 남음** | `src/terms/validator.py` |
| AI 조항 분석 (분류·요약·불공정 조항) | 코드 있음, 실제 LLM 미실행 | `src/terms/analyzer.py` |
| 사고보장 스키마 (정액 + **실손**) | 동작 | `src/schema/coverage.py` |
| 사고보장 추출: 묶음 → LLM → 근거 검증 → 정답 비교 | **코드·테스트 완료, 실제 LLM 미실행** | `src/coverage_extract/` |
| 약관 구조화 뷰어 (HTML) | 동작 | `tools/terms_viewer/` |

**해커톤에서 가장 먼저 할 일은 OpenAI 키를 넣고 실손 2605 《질병급여형》을 실제로 추출해서 정답과 비교하는 것**입니다 (5장).

## 2. 새 PC 환경 세팅 (Windows)

PowerShell 기준입니다. 설치 후에는 **터미널을 새로 열어야** `git`, `uv` 명령이 잡힙니다.

```powershell
# 1) Git, uv 설치
winget install --id Git.Git -e --source winget
winget install --id astral-sh.uv -e --source winget
# (터미널 새로 열기)

# 2) git 사용자 설정 (커밋 작성자)
git config --global user.name "hosung84lee"
git config --global user.email "<본인 이메일>"
git config --global core.quotepath false   # 한글 파일명이 \354\202… 처럼 깨지지 않게

# 3) 저장소 받기
cd D:\dev            # 원하는 작업 폴더
git clone https://github.com/hosung84lee/withGot
cd withGot

# 4) 파이썬 + 의존성 설치 (uv 가 .python-version 의 Python 3.12 도 알아서 받음)
uv sync

# 5) 환경 변수 파일
copy .env.example .env
notepad .env
```

`.env` 에서 바꿀 값 (앱은 OpenAI 전용, 팀원 PR #4):

```ini
OPENAI_API_KEY=sk-...             # 해커톤에서 받은 키
OPENAI_MODEL=gpt-6-luna           # 기본값. 쓸 모델 이름으로 바꿔도 됨
OPENAI_REASONING_EFFORT=none      # 설명은 .env.example 참고
```

`git push` 처음 할 때 브라우저로 GitHub 로그인 창이 뜹니다 (Git Credential Manager).

macOS 라면 `brew install git uv` 후 같은 순서이고, `copy` 대신 `cp .env.example .env`.

## 3. 세팅 확인

```powershell
# 빠른 테스트 (약 5초, 116개 통과 · 5개 건너뜀이 정상)
uv run pytest

# 실제 약관 PDF 테스트까지 (약 2분, 121개 통과가 정상)
uv run pytest --pdf

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

## 5. 해커톤에서 할 일 (추천 순서)

1. **실제 추출 1회** — 실손 2605 주계약 《질병급여형》 (묶음 1개, 약 7,700자)
   ```powershell
   uv run python -m coverage_extract "insurance-workbench/data/reference/policies/삼성생명_급여실손의료비보장보험_2605갱신형_약관_2026-09-23.pdf" `
       --section 질병급여형 --out out.json `
       --compare tests/fixtures/silson_2605_disease_covered.json
   ```
   출력의 `근거 확인 / 검토 필요` 와 `정답 비교: 값까지 일치 N%` 를 봅니다.
   다시 비교만 할 때는 `--ground out.json --compare …` (API 호출 없음).
2. **프롬프트 다듬기** — `src/coverage_extract/extractor.py` 의 `SYSTEM`, `PROMPT`.
   틀린 항목은 비교 결과의 `[값이 다름]`, `[빠짐]` 과 근거 검증의 `NUMBER_NOT_FOUND` 로 드러납니다.
3. **범위 넓히기** — `--section` 없이 8묶음 전체 (주계약 2 + 비급여 특약 6).
   정답 파일을 《상해급여형》·비급여로 늘리면 평가 범위도 넓어집니다.
4. **개정 비교** — 실손 2601 과 2605 를 각각 추출해 규칙 id 기준으로 비교 (설계: `coverage_schema.md` 6장).
5. **화면** — Streamlit 약관 분석 화면(`src/app/views/terms_page.py`)이나 뷰어에 "사고보장" 탭.
6. **정액형** — 암보험은 지급 금액이 별표에 있어 묶음에 인용 별표·정의 조를 넣는 확장이 필요.

## 6. 오늘 한 작업 (커밋 순서)

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

- 사고보장 추출은 **실제 LLM 으로 아직 돌려보지 않음** (테스트는 가짜 응답).
- 옆 안내 상자는 끝 표시가 없어 번호로 끝을 판단합니다. 상자 안 다음 번호와 본문 다음 번호가 같으면(상자 ①② 뒤 본문 ③) 구분 못 함. 실제 약관 7개에서는 문제 없었음.
- 번호 없는 각주 `(주)` 바로 뒤에 본문 `1.` 이 오면 각주 목록으로 볼 수 있음.
- 보장종목 구분은 끝 표시가 없어 다음 관에서 끝난 것으로 봅니다 (공통인 제4조의2 가 앞 보장종목에 붙음, 검증에는 영향 없음).
- AI 분석·사고보장의 조 표기는 `제3조` 처럼 표기만 써서, 특약이 여러 개면 어느 약관의 조인지 `part`/`section` 과 함께 봐야 합니다.

## 10. Claude Code 로 이어서 작업할 때

- 새 PC 의 Claude Code 는 이전 대화·메모리를 모릅니다. 저장소 최상위 `CLAUDE.md` 가 이 문서와 세부 문서를 가리키므로,
  첫 요청에서 "docs/HACKATHON.md 읽고 이어서 하자" 라고 하면 됩니다.
- 약관 구조화(`src/terms/`)를 고쳤으면 `uv run pytest --pdf` 로 실제 약관까지 확인하세요.
