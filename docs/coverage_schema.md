# 사고보장 Canonical Schema 설계 (초안)

약관(보통약관·특별약관·별표)에서 뽑아낸 보장 정보를 **시스템 기준정보로 쓸 수 있는 표준 JSON** 으로 표현하기 위한 설계입니다.
보험금 계산 툴(MCP)은 이 구조를 입력으로 받고, 검증 단계는 이 구조의 모든 항목이 약관 원문에 근거하는지 확인합니다.

- 모델 코드: [`src/schema/coverage.py`](../src/schema/coverage.py)
- 관련 문서: 약관 구조화·검증 [terms.md](terms.md), 약관에서 이 데이터를 뽑는 방법 [coverage_extract.md](coverage_extract.md), 테이블에 저장하는 구조 [coverage_tables.md](coverage_tables.md)

> 실제 업무 시스템의 사고보장 구조(보장 → 위험률 → 위험유형 → 급부)를 **개념만** 참고했습니다.
> 내부 테이블명·컬럼명·코드값은 이 저장소에 두지 않으며, 대응표가 필요하면 사내 문서에서 관리합니다.

## 1. 설계 원칙

1. **업무 구조를 따른다** — 상품 → 보장(특약) → 위험률 → 지급 규칙 → 급부. 기존 시스템 담당자가 바로 읽을 수 있는 계층.
2. **모든 항목에 근거를 단다** — 규칙·담보코드마다 `source`(약관 단위, 조, 항, 호, 별표, 원문 인용).
   근거가 확인되지 않은 항목은 자동 확정하지 않고 **보정 대상**(`status="needs_review"`)으로 둔다.
3. **계산은 AI가 아니라 툴이 한다** — 스키마에는 금액이 아니라 **규칙**(비율, 기간, 한도)만 담는다. 금액은 MCP 툴이 계산.
4. **비교할 수 있게 만든다** — 각 규칙에 안정적인 `id` 를 두어, 구·신 약관을 규칙 단위로 diff(개정 비교).

## 2. 업무 구조 ↔ 스키마

| 업무 개념 | 설명 | 스키마 |
|---|---|---|
| 상품 | 보험 상품 하나 (약관 한 벌) | `Product` |
| 보장 | 보험금 지급 단위. 약관에서는 보통약관·특별약관 하나 | `Coverage` |
| 위험률 | 청구사유(진단·수술·입원·사망 …) × 담보코드 | `Risk` |
| 위험유형 (급부계산유형) | 위험률 하나에 1:N. 조건이 다른 지급 규칙 하나 | `BenefitRule` |
| 조회 조건 | 사고자 구분(주피·종피), 지급 시 보험 상태 | `BenefitRule.insured_role`, `policy_status` |
| 참조 조건 | 면책·감액·공제 기간, 한도, 발생 구분 | `RuleConditions` |
| 특수 조건 | 진단 확정, 기지급 여부 등. 다른 규칙과 관계를 가질 수 있음 | `SpecialCondition` |
| 급부 | 급부 유형, 지급 기준, 비율(분자/분모), 최소·최대 | `Benefit` |
| 분할 지급 | 횟수, 주기 | `Installment` |
| 담보코드 | KCD 코드 묶음 (효력 기간, KCD 차수 포함) | `CoverageCode`, `KcdRange` |

정의 순서도 업무와 같습니다: **상품 → 위험률 → 지급 규칙(1:N) → 급부 매칭**.

## 3. 구조

```
Product
├─ name, insurer, version(판매 시작일)
├─ coverages[]                       Coverage  (보장 = 약관 단위)
│   ├─ id, name, kind(main|rider), source
│   └─ risks[]                       Risk
│       ├─ id, claim_reason(diagnosis|surgery|hospitalization|death|disability|…)
│       ├─ coverage_code             → coverage_codes[].code
│       └─ rules[]                   BenefitRule  (지급 규칙)
│           ├─ id, name
│           ├─ insured_role          primary|secondary|…
│           ├─ policy_status         지급 대상 보험 상태 (선택)
│           ├─ conditions            RuleConditions
│           │   ├─ exemption_days            면책기간 (예: 계약일부터 90일)
│           │   ├─ reduction {days, ratio}   감액기간·지급비율 (예: 1년 이내 50%)
│           │   ├─ deductible_days           공제일수 (예: 3일 초과 입원부터)
│           │   ├─ limit {per_event_days, total_days, count}
│           │   └─ occurrence                최초 1회 / 매회 …
│           ├─ special_conditions[]  {type: diagnosis_confirmed|prior_payment|…, related_rule_id}
│           ├─ benefit               Benefit
│           │   ├─ type              rate(가입금액 대비) | fixed | actual_cost
│           │   ├─ base              sum_insured(가입금액) | premium_paid | …
│           │   ├─ ratio {numerator, denominator}     예: 25/100
│           │   └─ min_amount, max_amount
│           ├─ installment?          {count, cycle_months}
│           ├─ source                SourceRef
│           └─ status                confirmed | needs_review
└─ coverage_codes[]                  CoverageCode  (담보코드 = KCD 묶음)
    ├─ code, name
    ├─ kcd[]  {start, end, level, kcd_version, valid_from, valid_to}
    └─ source                        (보통 별표, 예: '별표4 암 분류표')
```

`SourceRef`: `{part: "암진단특약", article: "제3조", paragraph: 1, item: null, appendix: null, quote: "…"}`

## 4. 예시

> 주피보험자가 유방암(담보코드 내 KCD)으로 진단 확정되면 가입금액의 25%를 지급.
> 계약일부터 90일 이내 진단은 지급하지 않음.

```json
{
  "coverages": [{
    "id": "cancer-dx", "name": "암진단특약", "kind": "rider",
    "risks": [{
      "id": "cancer-dx/diagnosis/breast", "claim_reason": "diagnosis", "coverage_code": "BREAST_CANCER",
      "rules": [{
        "id": "cancer-dx/diagnosis/breast/1", "name": "유방암 진단",
        "insured_role": "primary",
        "conditions": {"exemption_days": 90},
        "special_conditions": [{"type": "diagnosis_confirmed"}],
        "benefit": {"type": "rate", "base": "sum_insured", "ratio": {"numerator": 25, "denominator": 100}},
        "source": {"part": "암진단특약", "article": "제3조", "paragraph": 1,
                   "quote": "가입금액의 25%를 지급"},
        "status": "confirmed"
      }]
    }]
  }],
  "coverage_codes": [{
    "code": "BREAST_CANCER", "name": "유방암",
    "kcd": [{"start": "C50", "end": "C50"}],
    "source": {"part": "암진단특약", "appendix": "별표4", "quote": "유방의 악성신생물(C50)"}
  }]
}
```

## 5. 검증 규칙

| 구분 | 내용 | 결과 |
|---|---|---|
| 근거 | `source.quote` 가 `source` 위치(조·항·별표)의 원문에 있는가 | 없으면 `needs_review` |
| 근거 | `source` 의 약관 단위·조·항이 구조화 결과에 실제로 있는가 | 없으면 오류 |
| 참조 | `coverage_code` 가 `coverage_codes` 에 있는가, `related_rule_id` 가 있는 규칙인가 | 오류 |
| 형식 | KCD 코드 형식(`C50`, `C50.1`, `C500`), 범위 `start ≤ end` | 오류 |
| 별표 | 담보코드 KCD 범위가 근거 별표의 코드와 일치하는가 | 경고 |
| 정합성 | 비율 분모 > 0, 0 < 감액비율 < 1, 면책기간 ≤ 감액기간, id 중복 없음 | 오류 |

## 6. 개정 비교

구·신 약관을 각각 `Product` 로 만든 뒤 규칙 `id` 기준으로 비교합니다.

- 추가 / 삭제된 규칙
- 변경된 필드 (예: `exemption_days 90 → 0`, 담보코드 KCD 범위 변경, `ratio 50/100 → 100/100`)
- 각 변경점에 구·신 `source` 를 함께 표시

## 7. 실손보험 표현 (`Benefit.type="actual_cost"`)

실손 2605 약관을 기준으로 추가한 필드입니다. 정액형 필드는 그대로 두고 덧붙였습니다.

| 약관 내용 (실손 2605 주계약 《질병급여형》) | 표현 |
|---|---|
| 급여 입원: 본인부담금의 80% | `benefit.cost_type="covered"`, `benefit.ratio=80/100`, `risk.claim_reason="hospitalization"` |
| 급여 통원: 본인부담금 − max(1만원, 20%, 본인부담률×의료비) | `benefit.deductible={amounts:[10000], ratios:[20/100], copay_rate:true, pick:"max"}` |
| 의원은 1만원, 종합병원은 2만원 공제 | 규칙을 나누고 `conditions.facility` 에 의료기관 조건 |
| 통원 1회당 20만원, 연간 5천만원 이내에서 계약자 선택 | `conditions.limit.amounts=[{amount:200000, per:"visit", selectable:true}, {amount:50000000, per:"year", …}]` |
| 입원 자기부담이 연 200만원 넘으면 초과분 보상 | `benefit.copay_cap_annual=2000000` |
| 계약 종료 후 180일까지 보상 (통원 최대 90회) | `conditions.extension={days:180, max_visits:90}` |
| 건강보험 미적용 시 40% | 별도 규칙 + `special_conditions=[{type:"no_health_insurance"}]` |
| 보장종목 (질병급여형·상해급여형) | `risk.section`, `source.section` |
| 한도가 다른 조(제5조)에 있음 | `rule.extra_sources` |
| 보상하지 않는 KCD·항목·사유 | `coverage.exclusions[]` (`kind: kcd \| cost_item \| cause`, KCD 는 `coverage_codes` 참조, 예외는 `exception` 글) |
| 질병 전체를 보장 (담보코드 없음) | `risk.coverage_code` 비움 |

`LimitPer`: `visit`(통원 1회) · `day` · `stay`(1회 입원) · `year`(보험연도) · `daily_average` · `event`.
`CostType`: `covered`(급여) · `non_covered`(비급여) · `room_difference`(상급병실료 차액).

## 8. 열린 질문 (업무 확인 필요)

- 참조 조건 중 **공제일수**와 **감액일수**의 정확한 구분, **발생 구분** 코드의 의미
- 특수 조건 유형 목록 (진단 확정, 기지급 여부, 건강보험 미적용 외)
- 지급 보험 상태 값의 범위
- 실손 공제금액 산식(본인부담률 곱)과 보상 제외의 예외 조건을 계산 툴에 어떻게 넘길지
