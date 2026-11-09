"""사고보장 Canonical Schema (초안). 설계: docs/coverage_schema.md

상품 → 보장(특약) → 위험률 → 지급 규칙 → 급부. 모든 규칙·담보코드는 약관 근거(source)를 가집니다.
금액은 담지 않고 규칙(비율·기간·한도)만 담습니다. 계산은 계산 툴이 합니다.

정액형(진단·수술·입원일당)은 Benefit.type="rate"/"fixed", 실손형(실제 의료비)은 "actual_cost" 로
표현합니다. 실손형은 급여·비급여 구분(cost_type), 보상률(ratio), 공제금액(deductible),
금액 한도(Limit.amounts), 자기부담 연간 상한(copay_cap_annual), 계약 종료 후 연장 보상
(RuleConditions.extension), 보상 제외(Coverage.exclusions) 를 씁니다.
"""

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

ClaimReason = Literal[
    "diagnosis", "surgery", "hospitalization", "outpatient", "death", "disability", "other"
]
InsuredRole = Literal["primary", "secondary", "child", "other"]
RuleStatus = Literal["confirmed", "needs_review"]
# 실손 의료비 구분: 급여 / 비급여 / 상급병실료 차액
CostType = Literal["covered", "non_covered", "room_difference"]
# 금액 한도의 단위: 통원 1회 / 1일 / 1회 입원 / 연간(보험연도) / 1일 평균 / 사고 1건
LimitPer = Literal["visit", "day", "stay", "year", "daily_average", "event"]

KCD_PATTERN = re.compile(r"^[A-Z]\d{2}(\.?\d{1,2})?$")  # C50, C50.1, C501


class SourceRef(BaseModel):
    """약관 근거 위치. article 또는 appendix 중 하나는 있어야 합니다."""

    part: str = Field(description="약관 단위. 예: 보통약관, 암진단특약")
    section: str | None = Field(
        default=None, description="보장종목. 예: 질병급여형 (같은 번호의 조가 보장종목마다 있을 때)"
    )
    article: str | None = Field(default=None, description="예: 제3조, 제3조의2")
    paragraph: int | None = None
    item: int | None = None
    appendix: str | None = Field(default=None, description="예: 별표4")
    quote: str = Field(default="", description="원문 그대로의 인용")

    @model_validator(mode="after")
    def _has_location(self):
        if not self.article and not self.appendix:
            raise ValueError("article 또는 appendix 중 하나는 있어야 합니다.")
        return self


class Ratio(BaseModel):
    numerator: float
    denominator: float = 100

    @field_validator("denominator")
    @classmethod
    def _positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("분모는 0보다 커야 합니다.")
        return v

    @property
    def value(self) -> float:
        return self.numerator / self.denominator


class Reduction(BaseModel):
    """감액: 계약일부터 days 이내 사고는 ratio 만큼만 지급."""

    days: int = Field(gt=0)
    ratio: Ratio


class AmountLimit(BaseModel):
    """금액 한도. 예: 통원 1회당 20만원, 연간 5천만원."""

    amount: int = Field(gt=0, description="원")
    per: LimitPer
    selectable: bool = Field(
        default=False,
        description="이 금액 이내에서 계약자가 선택 ('…이내에서 계약자가 선택한 금액')",
    )


class Limit(BaseModel):
    per_event_days: int | None = None  # 1회 입원당 한도일수
    total_days: int | None = None  # 통산 한도일수
    count: int | None = None  # 지급 횟수 (예: 최초 1회 → 1)
    amounts: list[AmountLimit] = Field(default_factory=list)  # 금액 한도 (실손)


class Extension(BaseModel):
    """계약이 끝난 뒤에도 계속 중인 입원·통원을 보상하는 기간."""

    days: int = Field(gt=0, description="계약 종료일 다음날부터 일수 (예: 180)")
    max_visits: int | None = Field(default=None, gt=0, description="통원 최대 횟수 (예: 90)")


class RuleConditions(BaseModel):
    exemption_days: int | None = Field(default=None, ge=0, description="면책기간(일)")
    reduction: Reduction | None = None
    deductible_days: int | None = Field(default=None, ge=0, description="공제일수(일)")
    limit: Limit | None = None
    occurrence: Literal["first", "each"] | None = None
    facility: str | None = Field(
        default=None, description="의료기관 조건. 예: 의원·보건소·약국 / 종합병원·상급종합병원"
    )
    extension: Extension | None = None

    @model_validator(mode="after")
    def _exemption_before_reduction(self):
        if self.exemption_days and self.reduction and self.exemption_days > self.reduction.days:
            raise ValueError("면책기간이 감액기간보다 길 수 없습니다.")
        return self


class SpecialCondition(BaseModel):
    type: str = Field(description="예: diagnosis_confirmed, prior_payment")
    related_rule_id: str | None = None
    description: str = ""


class Deductible(BaseModel):
    """공제금액. 여러 기준 중 큰 금액(max) 등으로 정함.

    예: '1만원, 보장대상 의료비의 20% 또는 보장대상의료비에 건강보험 본인부담률을 곱한 금액 중 큰 금액'
    → amounts=[10000], ratios=[20/100], copay_rate=True, pick="max"
    """

    amounts: list[int] = Field(default_factory=list, description="정액 기준 (원)")
    ratios: list[Ratio] = Field(default_factory=list, description="보장대상 의료비 대비 비율")
    copay_rate: bool = Field(default=False, description="보장대상 의료비 × 건강보험 본인부담률")
    pick: Literal["max", "min", "sum"] = "max"

    @model_validator(mode="after")
    def _has_basis(self):
        if not self.amounts and not self.ratios and not self.copay_rate:
            raise ValueError("공제금액 기준(amounts, ratios, copay_rate)이 하나는 있어야 합니다.")
        return self


class Benefit(BaseModel):
    type: Literal["rate", "fixed", "actual_cost"]
    base: Literal["sum_insured", "premium_paid", "reserve", "medical_cost"] = "sum_insured"
    ratio: Ratio | None = None
    fixed_amount: int | None = None
    min_amount: int | None = None
    max_amount: int | None = None
    # --- 실손 (type="actual_cost")
    cost_type: CostType | None = None
    deductible: Deductible | None = None
    copay_cap_annual: int | None = Field(
        default=None, gt=0, description="자기부담 연간 상한 (원). 넘는 금액은 보상 (예: 200만원)"
    )

    @model_validator(mode="after")
    def _required_fields(self):
        if self.type == "rate" and self.ratio is None:
            raise ValueError("type=rate 이면 ratio 가 필요합니다.")
        if self.type == "fixed" and self.fixed_amount is None:
            raise ValueError("type=fixed 이면 fixed_amount 가 필요합니다.")
        if self.type == "actual_cost" and self.ratio is None and self.deductible is None:
            raise ValueError(
                "type=actual_cost 이면 ratio(보상률) 나 deductible(공제금액)이 필요합니다."
            )
        return self


class Installment(BaseModel):
    count: int = Field(gt=0)
    cycle_months: int = Field(gt=0)


class BenefitRule(BaseModel):
    """지급 규칙 하나 (위험유형). 위험률 하나에 여러 개."""

    id: str
    name: str
    insured_role: InsuredRole = "primary"
    policy_status: str | None = None
    conditions: RuleConditions = Field(default_factory=RuleConditions)
    special_conditions: list[SpecialCondition] = Field(default_factory=list)
    benefit: Benefit
    installment: Installment | None = None
    source: SourceRef
    # 한도처럼 다른 조에 있는 근거 (예: 보상률은 제3조, 연간 한도는 제5조)
    extra_sources: list[SourceRef] = Field(default_factory=list)
    status: RuleStatus = "needs_review"


class Risk(BaseModel):
    """위험률: 청구사유 × 담보코드. 실손처럼 질병 전체를 보장하면 coverage_code 는 비움."""

    id: str
    claim_reason: ClaimReason
    coverage_code: str | None = None
    section: str | None = Field(default=None, description="보장종목. 예: 질병급여형")
    rules: list[BenefitRule] = Field(default_factory=list)


class Exclusion(BaseModel):
    """보상하지 않는 사항. KCD 코드 묶음, 의료비 항목, 사유(고의 등)."""

    id: str
    kind: Literal["kcd", "cost_item", "cause"]
    description: str
    coverage_code: str | None = Field(
        default=None, description="kind=kcd 면 coverage_codes 의 code"
    )
    exception: str = Field(default="", description="다만 …은 보상 같은 예외 (원문 요약)")
    section: str | None = None
    source: SourceRef
    status: RuleStatus = "needs_review"


class Coverage(BaseModel):
    """보장 = 약관 단위 (보통약관 / 특별약관)."""

    id: str
    name: str
    kind: Literal["main", "rider"] = "rider"
    risks: list[Risk] = Field(default_factory=list)
    exclusions: list[Exclusion] = Field(default_factory=list)
    source: SourceRef | None = None


class KcdRange(BaseModel):
    start: str
    end: str
    level: int | None = None
    kcd_version: int | None = None
    valid_from: str | None = None
    valid_to: str | None = None

    @field_validator("start", "end")
    @classmethod
    def _kcd_format(cls, v: str) -> str:
        v = v.strip().upper()
        if not KCD_PATTERN.match(v):
            raise ValueError(f"KCD 코드 형식이 아닙니다: {v}")
        return v

    @model_validator(mode="after")
    def _ordered(self):
        if self.start.replace(".", "") > self.end.replace(".", ""):
            raise ValueError(f"KCD 범위가 거꾸로입니다: {self.start}~{self.end}")
        return self


class CoverageCode(BaseModel):
    """담보코드 = KCD 코드 묶음."""

    code: str
    name: str
    kcd: list[KcdRange] = Field(default_factory=list)
    source: SourceRef | None = None


class Product(BaseModel):
    name: str
    insurer: str = ""
    version: str = ""  # 판매 시작일 등
    coverages: list[Coverage] = Field(default_factory=list)
    coverage_codes: list[CoverageCode] = Field(default_factory=list)

    def rules(self) -> list[BenefitRule]:
        return [r for c in self.coverages for k in c.risks for r in k.rules]

    def exclusions(self) -> list[Exclusion]:
        return [e for c in self.coverages for e in c.exclusions]

    @model_validator(mode="after")
    def _references(self):
        ids = [r.id for r in self.rules()] + [e.id for e in self.exclusions()]
        dup = {i for i in ids if ids.count(i) > 1}
        if dup:
            raise ValueError(f"규칙 id 중복: {sorted(dup)}")
        codes = {c.code for c in self.coverage_codes}
        for c in self.coverages:
            for k in c.risks:
                if k.coverage_code and codes and k.coverage_code not in codes:
                    raise ValueError(
                        f"{k.id}: 담보코드 {k.coverage_code} 가 coverage_codes 에 없습니다."
                    )
                for r in k.rules:
                    for s in r.special_conditions:
                        if s.related_rule_id and s.related_rule_id not in ids:
                            raise ValueError(f"{r.id}: 관계 규칙 {s.related_rule_id} 가 없습니다.")
            for e in c.exclusions:
                if e.coverage_code and e.coverage_code not in codes:
                    raise ValueError(
                        f"{e.id}: 담보코드 {e.coverage_code} 가 coverage_codes 에 없습니다."
                    )
        return self
