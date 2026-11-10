# 사고보장 데이터 추출 (`src/coverage_extract/`)

구조화된 약관([terms.md](terms.md))에서 **보상 규칙과 보상하지 않는 사항**을 뽑아
[사고보장 Canonical Schema](coverage_schema.md)(`schema.coverage.Product`) JSON 으로 만듭니다.
지금은 **실손보험(실손 2605)** 을 기준으로 만들었습니다.

```
약관 PDF ─ terms.extract ─ terms.parser (구조화: 약관·보장종목·조·항·호)
   │
   ▼
[추출 묶음]  coverage_extract/bundles.py     보장 조를 약관 × 보장종목 단위로 묶음 (LLM 없음)
   ▼
[LLM 추출]   coverage_extract/extractor.py   묶음마다 지급 규칙·보상 제외를 JSON 으로 (OpenAI)
   ▼
[근거 검증]  coverage_extract/grounding.py   인용문·숫자가 원문에 있는지 확인 → confirmed / needs_review
   ▼
[정답 비교]  coverage_extract/compare.py     사람이 만든 정답 JSON 과 규칙 단위로 비교 (선택)
   ▼
[스키마 갭]  coverage_extract/gaps.py        원문에 있는데 데이터로 못 담은 것 → 스키마 확장 제안 (LLM 없음)
```

## 실행

```bash
# 1) 추출 묶음만 보기 — API 키 필요 없음
uv run python -m coverage_extract "insurance-workbench/data/reference/policies/삼성생명_급여실손의료비보장보험_2605갱신형_약관_2026-09-23.pdf" --dry-run

# 2) 정답 파일의 근거 확인 — API 키 필요 없음 (11건 모두 ✓ 가 나와야 정상)
uv run python -m coverage_extract "<위 PDF>" --ground tests/fixtures/silson_2605_disease_covered.json

# 3) OpenAI 로 주계약 《질병급여형》만 추출 → 저장 → 정답과 비교  (.env 에 OPENAI_API_KEY 필요)
uv run python -m coverage_extract "<위 PDF>" --section 질병급여형 \
    --out out.json --compare tests/fixtures/silson_2605_disease_covered.json

# 4) 저장해 둔 결과를 API 호출 없이 다시 검증·비교
uv run python -m coverage_extract "<위 PDF>" --ground out.json --compare tests/fixtures/silson_2605_disease_covered.json

# 5) 스키마 갭 분석 — API 키 필요 없음. --ground 를 주면 근거 없는 원문·빈 필드까지
uv run python -m coverage_extract "<위 PDF>" --gaps --ground tests/fixtures/silson_2605_disease_covered.json --out gaps.json
```

| 옵션 | 설명 |
|---|---|
| `--dry-run` | 묶음 목록(약관 · 보장종목, 글자 수, 포함된 조)만 출력 |
| `--ground FILE` | LLM 없이 FILE(사고보장 JSON, `--out` 결과 형식도 됨)의 근거만 확인 |
| `--model` | OpenAI 모델. 기본값 `.env` 의 `OPENAI_MODEL` |
| `--section 질병급여형` | 이 글자가 든 묶음만 추출 (여러 번 지정 가능). 비용·시간 절약용 |
| `--out out.json` | `{"product": …, "issues": […]}` 저장 |
| `--compare GOLDEN` | 결과를 정답 JSON 과 비교해서 일치율·차이 출력 |
| `--gaps` | 스키마 갭 분석 (5장). `--ground FILE` 과 함께 쓰면 그 데이터 기준으로 근거 없는 원문·빈 필드도 |

코드에서:

```python
from terms import parse_terms
from terms.extract import pdf_to_text
from coverage_extract import build_bundles
from coverage_extract.extractor import extract_coverage
from coverage_extract.grounding import ground_product
from coverage_extract.compare import compare_products

doc = parse_terms(pdf_to_text("실손2605.pdf"))
for b in build_bundles(doc):
    print(b.key, [a.label for a in b.articles])

report = extract_coverage(doc, sections=["질병급여형"])   # 모델 지정: model="gpt-6-luna"
report.product          # schema.coverage.Product
report.issues           # 근거 검증 문제 목록
report.confirmed, report.needs_review
```

## 1. 추출 묶음 (`bundles.py`)

- **보장 약관만**: 보장종목 구분(《질병급여형》)이 있거나 `보상내용`·`보험금의 지급사유` 조가 있는 약관.
  중지·재개, 지정대리청구, 장애인전환 같은 제도성 특약은 빠집니다.
- **묶음 = 약관 하나 × 보장종목 하나.** 보장종목이 없으면 약관 전체가 묶음 하나.
- **묶음에 넣는 조**: 그 보장종목의 조(제3조 보상내용, 제4조 보상하지 않는 사항) + 그 조가 인용한 같은 약관의
  공통 조(제5조 보험가입금액 한도 등) + 보장 조와 번호가 같은 `제N조의M`(제4조의2 등).
- 실손 2605 결과 (8묶음, 묶음당 7~10천 자):

| 약관 | 보장종목 |
|---|---|
| 주계약 (급여) | 질병급여형, 상해급여형 |
| 비중증 비급여 특약D | 질병비급여형, 상해비급여형, 비급여자기공명영상진단형 |
| 중증 비급여 특약D | 질병비급여형, 상해비급여형, 3대비급여형 |

## 2. LLM 추출 (`extractor.py`)

- `agent.Agent` + `terms.analyzer.ask_json` 재사용: JSON 형식이 틀리면 에러를 알려주고 다시 받음(최대 3번).
- 프롬프트(`SYSTEM`, `PROMPT`)에 스키마 예시와 규칙이 있음: 금액은 원 단위 정수, 비율은 분자/분모,
  모든 규칙에 `source`(약관·보장종목·조·항·원문 인용), 한도처럼 다른 조 근거는 `extra_sources`.
- LLM 이 준 id 는 버리고 코드가 다시 매김: `p0/질병급여형/hospitalization1/1`, `p0/질병급여형/exclusion1`,
  담보코드 `p0/질병급여형/<code>`. 같은 약관을 다시 돌려도 id 가 같아서 개정 비교에 쓸 수 있습니다.
- LLM 이 `status: confirmed` 를 줘도 `needs_review` 로 되돌린 뒤 근거 검증으로만 확정합니다.

## 3. 근거 검증 (`grounding.py`)

| 코드 | 수준 | 내용 |
|---|---|---|
| `SOURCE_NOT_FOUND` | error | source 의 약관·보장종목·조(또는 별표)가 구조화 결과에 없음 |
| `PARAGRAPH_NOT_FOUND` | warning | source 의 항이 그 조에 없음 |
| `QUOTE_NOT_FOUND` | warning | 인용문이 그 조 원문에 없음 (공백·줄바꿈·따옴표·가운뎃점 차이는 무시) |
| `NUMBER_NOT_FOUND` | warning | 규칙의 숫자가 근거 조들(source + extra_sources) 원문에 없음 |

- 숫자 확인 대상: 보상률(80%), 지급금액, 자기부담 연간 상한(200만원), 공제금액·공제비율(1만원·20%),
  금액 한도(20만원·5천만원), 연장 보상(180일·90회), 면책·감액 기간.
- 원문 숫자 읽기: `5천\n만원`(줄바꿈) → 50,000,000, `1 만원` → 10,000, `80%`, `180일`, `90회`.
- 문제가 하나도 없으면 `confirmed`, 하나라도 있으면 `needs_review`.
  **confirmed 는 "원문에 근거가 있다"는 뜻이지 업무 검토가 끝났다는 뜻이 아닙니다.**

## 4. 정답 파일과 비교 (`compare.py`)

- `tests/fixtures/silson_2605_disease_covered.json`: 실손 2605 주계약 《질병급여형》 정답 (사람이 원문 대조).
  규칙 4개(급여 입원 80%, 급여 통원 의원 1만원 공제, 급여 통원 종합병원 2만원 공제, 건강보험 미적용 40%)
  + 보상 제외 7개(F04~F99, N96~N98, O00~O99, Q00~Q04, 요실금, 간병비, 고의 자해). 실제 PDF 로 근거 검증 11/11.
- 비교는 id·이름·인용문이 아니라 **내용**으로 짝을 맞춥니다.
  - 규칙 키: 보장종목, 청구사유, 의료비 구분, 공제 정액, 특수 조건
  - 비교 값: 보상률, 공제(정액·비율·본인부담률), 금액 한도, 자기부담 상한, 연장 보상
  - 보상 제외 키: (종류, KCD 범위) 또는 (종류, 설명)
- 출력: 일치 / 값이 다름(무엇이 다른지) / 빠짐 / 정답에 없음, 그리고 일치율(정답 항목 중 값까지 맞힌 비율).

## 5. 스키마 갭 분석 (`gaps.py`)

추출 결과가 스키마에 **잘 들어간 것**만 보면, 스키마가 표현하지 못해 버려진 내용은 보이지 않습니다.
갭 분석은 반대로 **약관 원문에서 출발**해서 데이터로 담지 못한 것을 찾고, 스키마를 어떻게 넓혀야 하는지 제안합니다.

| 결과 | 무엇을 찾나 | 어떻게 |
|---|---|---|
| 개념 갭 | 원문에 나오는 보상 규칙 개념 중 스키마에 자리가 없거나(구조 확장·필드 추가) 글로만 담기는(부분 표현) 것 | 개념 목록(`CONCEPTS`)의 문구 패턴을 묶음의 항·호에서 찾음. 공통 조(제5조)는 한 번만 |
| 근거 없는 원문 | 데이터가 있는 묶음에서 어떤 규칙·보상 제외도 인용하지 않은 항·호 | 인용문이 그 항·호에 있는지. '다음과 같습니다' 같은 안내 문장은 뺌 |
| 빈 필드 | 스키마에 필드는 있는데 원문 값이 데이터에 없음 | 예: 원문에 KCD 차수가 있는데 `kcd_version` 이 비어 있음 |

근거 없는 항·호는 **빠진 이유**로 나눕니다. 이 구분이 "스키마를 넓힐지, 추출을 고칠지"를 정합니다.

| 이유 | 뜻 | 할 일 |
|---|---|---|
| `schema_gap` | 그 항·호에 스키마에 자리가 없는 개념(구조 확장·필드 추가)이 있음 | **스키마 확장** |
| `uncited_value` | 그 항·호의 숫자(180일 등)가 데이터에 이미 있는데 근거로 인용하지 않음 | 근거(`extra_sources`) 보완 |
| `extraction_gap` | 지금 스키마로 담을 수 있는데 데이터에 없음 (예: 성장호르몬 제외 → `Exclusion(kind="cost_item")`) | 추출 프롬프트·정답 보완 |

### 실손 2605 결과

개념 갭 16종 (묶음 8개 전체):

| 종류 | 개념 | 원문 | 제안 |
|---|---|---|---|
| 구조 확장 | 여러 보상의 합산 한도 (입원+통원 합산 5천만원) | 5곳 | `LimitPool{amount, per, members}` |
| 구조 확장 | 1회 산정 규칙 (같은 날 외래+처방 = 1회, 치료행위·부위별 1회) | 12곳 | `CountingRule{unit, merge_when, deductible_on_merge}` |
| 구조 확장 | 사고 단위 정의 ("하나의 질병", "1회 입원") | 4곳 | `EventDefinition` + 규칙에서 참조 |
| 구조 확장 | 단계적 보장 (최초 10회 후 개선 확인 시 10회 단위, 연 50회) | 1곳 | `Limit.stages{initial, step, max, requires}` |
| 구조 확장 | 다른 보장종목으로 이관 (항암제 주사료 → 《질병비급여형》) | 1곳 | `redirect_to{section, article}` |
| 필드 추가 | '연간'의 기준 (보험연도) | 5곳 | `AmountLimit.period_basis` |
| 필드 추가 | 연장 보상의 잔여 한도 (연간 한도 − 이미 지급액) | 4곳 | `Extension.limit_basis` |
| 필드 추가 | 감면받은 의료비의 계산 기준 (감면 후/전) | 18곳 | `Benefit.reduction_basis` |
| 필드 추가 | 기간이 정해진 보상 제외 (가입일부터 2년 이내) | 1곳 | `Exclusion.within_days` |
| 필드 추가 | 피보험자 조건 (가입 당시 태아, 18세까지) | 8곳 | `Condition.insured{at_entry, age_max}` |
| 필드 추가 | 갱신·전환·재가입 시 처리 | 11곳 | `Condition.contract_history` |
| 필드 추가 | 대상 질환 조건 (산정특례) | 6곳 | `Risk.eligibility` |
| 필드 추가 | 보상 대상 비용 항목 (행위료·약제비…, 입원실료·입원수술비) | 7곳 | `Benefit.included_items[]` |
| 부분 표현 | 보상 제외의 예외 ("다만 …은 보상") | 39곳 | `ExclusionException{kcd, cost_type, insured_condition, age_limit}` |
| 부분 표현 | 연간 횟수 한도 (350만원 이내에서 50회까지) | 1곳 | `Limit.count_per` + 금액 한도와 결합 |
| 부분 표현 | KCD 차수 (제9차 KCD, 이후 개정 포함) | 5곳 | `kcd_version` 채우기 |

정답 데이터(《질병급여형》) 기준: 항·호 36개 중 **12개만 인용(33%)**. 나머지 24개의 이유는
스키마 확장 필요 8 · 근거 인용 보완 2 · 추출·정답 보완 14. 빈 필드 1 (`kcd_version`).

- 개념 목록은 실손 2605 묶음 8개에서 실제로 본 문구로 만들었습니다. 다른 약관(암보험 등)에서는 목록에 없는 개념이
  '근거 없는 원문 · extraction_gap' 으로 드러나므로, 그 항·호를 보고 새 개념을 `CONCEPTS` 에 추가합니다.
- 패턴은 문구 기반이라 같은 개념을 다른 말로 쓰면 놓칠 수 있습니다. LLM 추출 때 "스키마에 못 담은 내용" 칸을 함께
  받도록 확장하면 보완됩니다 (다음 할 일).

## 테스트

| 파일 | 내용 |
|---|---|
| `tests/test_coverage_extract.py` | 묶음, 숫자 읽기, 가짜 LLM 응답으로 추출·id 재지정·근거 검증(인용·숫자·조 오류), 재시도, 정답 비교, 명령 |
| `tests/test_coverage_schema.py` | 스키마 형식·참조·정합성 |
| `test_real_silson_2605_golden_is_grounded` (`--pdf`) | 실제 PDF 로 정답 파일 근거 11/11, 묶음 8개 |
| `tests/test_coverage_gaps.py` | 개념 갭 찾기, 공통 조 한 번만, 보상 제외 전용 개념, 빠진 이유 3가지, 명령. `--pdf`: 실손 2605 수치(16종, 36/12, 8·2·14) |

## 한계와 다음 할 일

- **실제 LLM 으로는 아직 한 번도 돌려보지 않았습니다.** 테스트는 모두 가짜 응답입니다.
  해커톤 첫 작업: `--section 질병급여형 --compare` 로 돌려서 일치율 확인 → 프롬프트 다듬기.
- 정답 파일은 《질병급여형》만 있습니다. 《상해급여형》, 비급여 특약으로 정답을 늘리면 평가 범위가 넓어집니다.
- 보상금액 **표**가 텍스트 추출에서 평평해집니다(`구 분 보 상 금 액 / 입원 … 80%에 해당하는 금액`).
  LLM 이 칸을 헷갈리면 NUMBER_NOT_FOUND·비교 결과로 드러납니다. 필요하면 PyMuPDF 표 추출 검토.
- **정액형(암보험 등)** 은 지급 금액이 별표(보험금 지급기준표)에 있어서 지금 묶음(조만 넣음)으로는 부족합니다.
  묶음에 인용된 별표·정의 조(제2조의N "암"의 정의)를 넣는 확장이 필요합니다.
- 보상 제외의 예외("다만 F20~F29 요양급여는 보상")는 `exception` 글로만 둡니다 (구조화 안 함). 갭 분석의 `STRUCTURED_EXCEPTION`.
- 갭 분석이 제안한 스키마 확장(5장)은 아직 스키마에 반영하지 않았습니다. 우선순위 제안: 합산 한도 → 1회 산정 규칙 → 보상 제외의 예외 구조화.
- 개정 비교(2601 ↔ 2605)는 설계만 있음: 둘 다 추출한 뒤 규칙 id 기준 diff 를 만들면 됩니다.
