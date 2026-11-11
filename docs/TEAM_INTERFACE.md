# 팀 인터페이스 명세 (해커톤 H0 확정용 초안)

3명이 **기다리지 않고 동시에** 개발하기 위한 계약입니다. 해커톤 첫 1시간(H0)에 셋이 함께 읽고 확정합니다.
확정한 뒤에는 `src/schema/` 에 Pydantic 모델로 옮기고 잠급니다 (바꿀 때는 셋이 합의).

- 사고보장 데이터 구조: [coverage_schema.md](coverage_schema.md) · 테이블: [coverage_tables.md](coverage_tables.md)
- 약관 구조화·추출·근거 검증·갭 분석: [REBUILD_GUIDE.md](REBUILD_GUIDE.md), [coverage_extract.md](coverage_extract.md)
- 에이전트 규칙 템플릿: [hackathon_templates/](hackathon_templates/)

## 1. 역할과 흐름

```
[약관]  약관 PDF ─▶ 구조화 ─▶ 묶음 ─▶ LLM 추출 ─▶ 근거 검증 ─▶ 갭 분석
                                                   │
                                     ① 사고보장 JSON (Product) + ② AI 판단 항목 + ③ escalations
                                                   ▼
[보험금] 청구정보(시나리오) ④ ─▶ 보장 매칭 ─▶ 계산 툴(결정론) ─▶ AI 판단 위임 ─▶ ⑤ 계산 결과
                                                   ▼
[앱]    약관 업로드·구조 보기 → 데이터·근거·갭 검토 → 시나리오 입력 → 지급액·근거 → 심사자 승인/수정/반려
```

| 역할 | 맡는 것 | 만드는 계약 | 쓰는 계약 |
|---|---|---|---|
| **약관** | 구조화·추출·근거 검증·갭 분석, (추가) 개정 비교 | ① ② ③ | — |
| **보험금** | 보장 매칭, 계산 툴(MCP), AI 판단 위임, 계산 정답 데이터 | ④(형식) ⑤ | ① ② |
| **앱** | 화면·흐름, 진행 표시, 검토·승인, 저장 | 화면 ↔ 워크플로 공개 함수 | ① ③ ④ ⑤ |

**원칙**: 금액은 `int`(원), 비율은 `{numerator, denominator}`(감액 50%, 본인부담률 등 정수가 아닌 비율 때문),
날짜는 `YYYY-MM-DD`. LLM 은 금액·날짜를 계산하지 않고 지급 여부를 정하지 않습니다.

## 2. 계약 ① 사고보장 JSON (`Product`) — 약관 → 보험금·앱

[coverage_schema.md](coverage_schema.md) 의 `schema.coverage.Product` 그대로입니다. **예시 파일 두 개로 바로 시작합니다.**

| 파일 | 내용 | 상태 |
|---|---|---|
| `tests/fixtures/silson_2605_disease_covered.json` | 실손 2605 《질병급여형》 규칙 4 + 보상 제외 7 | 원문 대조 완료, 근거 11/11 |
| `tests/fixtures/cancer_2404_diagnosis_draft.json` | 인터넷암보험 2404 암진단Ⅰ·Ⅱ·Ⅲ + 소액암 2 + 보상 제외 3 | **초안**, 근거 8/8, 팀원 확인 필요 |

보험금 담당이 꼭 알아야 할 표현:

| 약관 | JSON |
|---|---|
| 가입금액의 40% | `benefit: {type: "rate", base: "sum_insured", ratio: {numerator: 40, denominator: 100}}` |
| 계약일부터 1년 이내 50% 지급 | `conditions.reduction: {days: 365, ratio: 50/100}` (정확히는 "1년이 되는 계약해당일 전일까지") |
| 암보장개시일 = 계약일 포함 90일이 지난날의 다음날 | `conditions.exemption_days: 90` → 계약일 + 90일이 보장 시작일 |
| 최초 1회 | `conditions.occurrence: "first"` |
| 실손 통원 공제 = max(1만원, 20%, 본인부담률 금액) | `benefit.deductible: {amounts: [10000], ratios: [20/100], copay_rate: true, pick: "max"}` |
| 통원 1회당 20만원, 연간 5천만원 (계약자 선택) | `conditions.limit.amounts: [{amount: 200000, per: "visit", selectable: true}, {amount: 50000000, per: "year", …}]` |
| 대상 질병 | `risk.coverage_code` → `coverage_codes[].kcd[{start, end}]` |

**지금 스키마로 못 담아 `special_conditions` 설명(글)으로 둔 것** — 보험금 담당은 이 글을 코드로 판정하지 말고 ② AI 판단 항목이나 ③ escalations 로 다룹니다:
Ⅰ·Ⅱ·Ⅲ 합산 지급, 대상 중 일부 제외(전립선암 제외 등), 병기·조직형 기준(초기유방암 = AJCC 1기), 성별 조건, 재발·전이 부지급.

## 3. 계약 ② AI 판단 항목 — 약관 → 보험금

KCD·금액·날짜만으로 정할 수 없어서 **서류를 읽고 판단해야 하는 조건**입니다. 약관 담당이 추출 때 정의하고, 보험금 담당이 청구 시 Agent 에 위임합니다.

```json
{
  "code": "BREAST_EARLY_STAGE",
  "name": "초기유방암 여부",
  "description": "유방암(C50) 중 AJCC 제8판 TNM 해부병기 1기(T1N0M0, T0N1miM0, T1N1miM0)인지",
  "rule_ids": ["p0/diagnosis2/1", "p0/diagnosis4/1"],
  "clause_ref": {"part": "삼성 인터넷암보험(2404)(갱신형,무배당) 약관", "article": "제2조의3", "paragraph": 1,
                 "quote": "유방암의 TNM 해부(anatomic)병기 분류상 1기(Stage1)"},
  "output_schema": {"result": "yes | no | unknown"}
}
```

판단 결과 (보험금 → 앱):

```json
{
  "code": "BREAST_EARLY_STAGE",
  "result": "no",
  "description": "병리 결과지에 pT2N0M0 로 기재되어 1기가 아님",
  "refs": [{"kind": "document", "path": "data/claims/S004/pathology.png", "page": 1}],
  "status": "needs_review"
}
```

- `result` 가 `unknown`(서류 부족·근거 불충분)이면 사람 검토 대상입니다.
- 원본 구성안의 `adjustResult / adjustDescription / adjustRef` 는 위 `result / description / refs` 에 해당합니다.
  JSON 이름 규칙(snake_case 또는 camelCase + alias)은 H0 에 하나로 정합니다.

## 4. 계약 ③ escalations — 약관 → 앱 (+ 보험금)

**스키마에 없는 항목은 값을 지어내지 않고 여기로 보냅니다.** 규칙 기반 갭 분석(`coverage_extract.gaps`)과 LLM 추출이
같은 형식을 씁니다.

```json
{
  "code": "SHARED_LIMIT",
  "item": "입원과 통원의 보상금액을 합산한 연간 한도",
  "source": {"part": "삼성 급여 실손의료비보장보험(2605)(갱신형, 무배당) 약관", "article": "제5조", "paragraph": 1,
             "quote": "입원과 통원의 보상금액을 합산하여 5천만원 이내에서"},
  "reason": "규칙마다 같은 연간 한도를 복사하면 합산된다는 사실이 사라짐",
  "proposal": "LimitPool{id, amount, per, members:[rule_id]}",
  "origin": "gap_rule"
}
```

- `code`: 갭 분석 개념 코드(26종, [coverage_extract.md 5장](coverage_extract.md)) 또는 LLM 이 찾은 새 항목은 `NEW`.
- `origin`: `gap_rule`(규칙 기반) | `llm`(추출 중 LLM 보고). 둘 다 같은 원문 위치를 가리키면 하나로 합쳐 보여 줌.

## 5. 계약 ④ 청구정보 (시나리오) — 앱 → 보험금

해커톤 기본 입력은 **화면에서 입력하는 시나리오 JSON**입니다 (서류 이미지 → 청구정보 추출은 추가 목표).

```json
{
  "claim_id": "S001",
  "product_id": "cancer-2404",
  "insured": {"sex": "M", "birth_date": "1985-03-02", "fetus_at_entry": false},
  "contract": {
    "contract_date": "2026-01-10", "first_contract_date": "2026-01-10", "renewal": false,
    "sum_insured": 30000000,
    "selected_limits": {"LIMIT_AMT_YEAR": 50000000, "LIMIT_AMT_VISIT": 200000}
  },
  "events": [
    {"type": "diagnosis", "date": "2026-11-02", "kcd": "C16.9", "attributes": {}}
  ],
  "history": {"paid": [], "paid_ytd": 0, "copay_ytd": 0}
}
```

`events[].type` 별 필드:

| type | 필드 |
|---|---|
| `diagnosis` | `date`, `kcd`, `attributes` (예: `{"ajcc_stage": "T1N0M0", "histology": "papillary"}` — AI 판단 입력) |
| `outpatient` | `date`, `kcd`, `facility`: `clinic`(의원·보건소·약국) \| `hospital` \| `general_hospital` \| `tertiary`, `costs` |
| `hospitalization` | `admit_date`, `discharge_date`, `kcd`, `costs` |
| `surgery` | `date`, `kcd`, `procedure_code`, `procedure_name` |

`costs`: `{"covered_copay": 35000, "covered_full_copay": 0, "non_covered": 0, "copay_rate": {"numerator": 30, "denominator": 100}}`
(급여 일부 본인부담금, 급여 전액본인부담금, 비급여, 건강보험 본인부담률 — 진료비 영수증 항목)

## 6. 계약 ⑤ 계산 결과 — 보험금 → 앱

```json
{
  "claim_id": "S001",
  "items": [
    {
      "rule_id": "p0/diagnosis3/1",
      "rule_name": "암진단보험금Ⅲ",
      "event_index": 0,
      "decision": "pay",
      "amount": 18000000,
      "steps": [
        {"name": "대상 질병", "detail": "C16.9 ∈ 담보코드 CANCER (C15-C26), 제외 대상 아님", "result": "pass",
         "source": {"part": "…", "appendix": "별표 2", "quote": "악성신생물로 분류되는 질병"}},
        {"name": "보장개시일", "detail": "계약일 2026-01-10 + 90일 → 2026-04-10 이후 진단", "result": "pass",
         "source": {"part": "…", "article": "제2조의9", "paragraph": 1, "quote": "그 날을 포함하여 90일이 지난날의 다음날"}},
        {"name": "감액", "detail": "2027-01-09 까지 1년 이내 → 50%", "result": "reduced",
         "source": {"part": "…", "article": "제4조", "paragraph": 5, "quote": "…보험금의 50%를 지급합니다"}},
        {"name": "지급액", "detail": "30,000,000 × 120/100 × 50/100", "value": 18000000}
      ],
      "judgments": []
    }
  ],
  "total": 30000000,
  "escalations": []
}
```

(위 예시는 7장 S001 이고 Ⅲ 항목만 적었습니다. Ⅰ·Ⅱ 항목(각 600만원)이 같은 모양으로 더 있어 `total` 이 3,000만원입니다.)

- `decision`: `pay` | `no_pay` | `review`(AI 판단 `unknown` 이거나 escalation 이 걸림).
- 모든 `steps[].source` 는 ① 의 `source`·`extra_sources` 에 있는 것만 씁니다 (새로 만들지 않음).
- 계산 툴(MCP) 하나 = 급부 유형 하나: `calc_fixed_rate`(정액, 감액·면책), `calc_actual_cost`(실손, 공제·보상률·한도).
  같은 입력이면 항상 같은 결과.

## 7. 계산 정답 예시 (보험금 담당이 첫날부터 테스트에 쓰기)

가입금액 3,000만원, 계약일 2026-01-10 (최초계약, 갱신 아님). **팀원이 약관과 다시 맞춰 확정하세요.**

| # | 상품 | 사건 | 기대 결과 | 핵심 규칙 |
|---|---|---|---|---|
| S001 | 암 | 2026-11-02 위암(C16.9) 진단 | Ⅰ 600만 + Ⅱ 600만 + Ⅲ 1,800만 = **3,000만** | 1년 이내 50%, Ⅰ·Ⅱ·Ⅲ 합산 |
| S002 | 암 | 2027-03-02 위암 진단 | 1,200 + 1,200 + 3,600 = **6,000만** | 1년 초과 |
| S003 | 암 | 2026-04-09 위암 진단 | **0** (암보장개시일 2026-04-10 전) | 90일 면책 (경계: 04-10 이면 S001 과 같은 계산) |
| S004 | 암 | 2027-03-02 유방암(C50), 병리 pT2N0M0 | Ⅰ 1,200 + Ⅱ 1,200 = **2,400만** (Ⅲ 제외 대상) | AI 판단: 초기유방암 아님 |
| S005 | 암 | 2027-03-02 갑상선암(C73) 유두암 | 소액암 ① **720만** (암 아님) | AI 판단: 중증 이외 갑상선암 |
| S006 | 암 | S001 이후 2027-05-01 위암 재발 | **0** | 이미 지급된 암의 재발 |
| S101 | 실손 | 의원 외래, 급여 본인부담 35,000원, 본인부담률 30% | 공제 max(10,000, 7,000, 10,500) = 10,500 → **24,500원** | 통원 공제 |
| S102 | 실손 | 종합병원 외래, 급여 본인부담 180,000원, 본인부담률 30% | 공제 max(20,000, 36,000, 54,000) = 54,000 → **126,000원** | 통원 공제, 회당 20만 이내 |
| S103 | 실손 | 입원, 급여 본인부담 1,000,000원 | **800,000원** (자기부담 20만) | 입원 80% |

> S101·S102 의 '본인부담률 금액'은 "보장대상의료비 × 건강보험 본인부담률"을 급여 본인부담금 × 본인부담률로 둔 해석입니다.
> 약관 (주)의 본인부담률 정의(급여 일부 본인부담금 ÷ (그것 + 공단부담금))와 영수증 항목으로 다시 확인하세요.

## 8. 화면 ↔ 워크플로 공개 함수 (앱 ↔ 약관·보험금)

앱은 아래 함수만 부릅니다. 모두 `on_progress(step: str, message: str)` 콜백을 받고, streamlit 을 import 하지 않습니다.

```python
# workflow/policy/__init__.py  (약관)
def run_policy(pdf_path: str, *, sections: list[str] | None = None, on_progress=None) -> PolicyResult
# PolicyResult: product(①), judgments(②), escalations(③), grounding_issues, trace_id

# workflow/claim/__init__.py  (보험금)
def run_claim(claim: ClaimInput, product: Product, judgments: list[JudgmentItem], *, on_progress=None) -> CalcResult
```

## 9. 폴더와 담당 (새 저장소)

```
src/schema/        coverage.py(①) judgment.py(②) escalation.py(③) claim.py(④) calc.py(⑤)   공동 · 잠금
src/workflow/policy/   src/agent/policy/   src/skills/                                      약관
src/workflow/claim/    src/agent/claim/    src/mcp_server/                                  보험금
src/app/   src/backend/                                                                     앱
src/data/golden/   (정답: 약관 JSON, 계산 시나리오)                                          사람만 수정
src/data/mock/     (①~⑤ 예시 — 앱·보험금이 첫날 바로 쓰는 가짜 데이터)                       앱
```

## 10. 시작 순서와 통합 시점

| 시점 | 약관 | 보험금 | 앱 |
|---|---|---|---|
| H0 (1시간) | 이 문서 확정 → `schema/` 모델 작성, `data/mock/` 에 7장 예시 넣기 (셋이 함께) | | |
| 1일차 | 구조화 → 실손 《질병급여형》 첫 실제 추출 + 정답 일치율 | `calc_actual_cost` (mock ①로) + S101~S103 통과 | 화면 뼈대 + mock 표시 |
| **1일차 저녁** | **1차 통합: 실제 추출 결과 → 계산 → 화면 한 줄** | | |
| 2일차 오전 | 암진단 추출(묶음에 별표·정의 조 확장) + 갭 분석 → escalations | `calc_fixed_rate` + S001~S006, AI 판단 위임 | 검토·승인 화면, 근거 표시 |
| **2일차 점심** | **2차 통합 + 정답 일치율 측정** | | |
| 2일차 오후 | 발표 준비, 시간 남으면 개정 비교 | | |

## 11. H0 에 정할 것 (체크리스트)

- [ ] 해커톤 기간(1일/2일)과 범위: 흐름 2 입력은 시나리오 JSON (서류 이미지는 추가 목표)
- [ ] 계산 툴은 **고정 툴**(`calc_fixed_rate`, `calc_actual_cost`) — 계산 코드 자동 생성은 추가 목표
- [ ] 스택: Python 버전, 패키지 관리(uv), PDF(pypdf), LLM(받은 키 기준 하나)
- [ ] JSON 이름 규칙(snake_case / camelCase + alias)
- [ ] 이 문서 ①~⑤ 확정 → `src/schema/` 작성·잠금, 스키마 변경 절차(누가 고치는지)
- [ ] 정답 데이터 담당: 약관 정답(약관), 계산 정답 30건(보험금)
- [ ] 브랜치 전략(main 직접 / PR), 커밋 태그 `[policy] [claim] [app]`
- [ ] 발표 시연 시나리오 하나 (예: S001 위암 → 3,000만원 + 근거 조항 + 갭 분석)
