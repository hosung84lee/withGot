"""사고보장 Canonical Schema (초안). 설계: docs/coverage_schema.md

상품 → 보장(특약) → 위험률 → 지급 규칙 → 급부. 모든 규칙·담보코드는 약관 근거(source)를 가집니다.
금액은 담지 않고 규칙(비율·기간·한도)만 담습니다. 계산은 계산 툴이 합니다.
"""

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

ClaimReason = Literal[
    "diagnosis", "surgery", "hospitalization", "outpatient", "death", "disability", "other"
]
InsuredRole = Literal["primary", "secondary", "child", "other"]
RuleStatus = Literal["confirmed", "needs_review"]

KCD_PATTERN = re.compile(r"^[A-Z]\d{2}(\.?\d{1,2})?$")  # C50, C50.1, C501


class SourceRef(BaseModel):
    """약관 근거 위치. article 또는 appendix 중 하나는 있어야 합니다."""

    part: str = Field(description="약관 단위. 예: 보통약관, 암진단특약")
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


class Limit(BaseModel):
    per_event_days: int | None = None  # 1회 입원당 한도일수
    total_days: int | None = None  # 통산 한도일수
    count: int | None = None  # 지급 횟수 (예: 최초 1회 → 1)


class RuleConditions(BaseModel):
    exemption_days: int | None = Field(default=None, ge=0, description="면책기간(일)")
    reduction: Reduction | None = None
    deductible_days: int | None = Field(default=None, ge=0, description="공제일수(일)")
    limit: Limit | None = None
    occurrence: Literal["first", "each"] | None = None

    @model_validator(mode="after")
    def _exemption_before_reduction(self):
        if self.exemption_days and self.reduction and self.exemption_days > self.reduction.days:
            raise ValueError("면책기간이 감액기간보다 길 수 없습니다.")
        return self


class SpecialCondition(BaseModel):
    type: str = Field(description="예: diagnosis_confirmed, prior_payment")
    related_rule_id: str | None = None
    description: str = ""


class Benefit(BaseModel):
    type: Literal["rate", "fixed", "actual_cost"]
    base: Literal["sum_insured", "premium_paid", "reserve", "medical_cost"] = "sum_insured"
    ratio: Ratio | None = None
    fixed_amount: int | None = None
    min_amount: int | None = None
    max_amount: int | None = None

    @model_validator(mode="after")
    def _required_fields(self):
        if self.type == "rate" and self.ratio is None:
            raise ValueError("type=rate 이면 ratio 가 필요합니다.")
        if self.type == "fixed" and self.fixed_amount is None:
            raise ValueError("type=fixed 이면 fixed_amount 가 필요합니다.")
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
    status: RuleStatus = "needs_review"


class Risk(BaseModel):
    """위험률: 청구사유 × 담보코드."""

    id: str
    claim_reason: ClaimReason
    coverage_code: str
    rules: list[BenefitRule] = Field(default_factory=list)


class Coverage(BaseModel):
    """보장 = 약관 단위 (보통약관 / 특별약관)."""

    id: str
    name: str
    kind: Literal["main", "rider"] = "rider"
    risks: list[Risk] = Field(default_factory=list)
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

    @model_validator(mode="after")
    def _references(self):
        ids = [r.id for r in self.rules()]
        dup = {i for i in ids if ids.count(i) > 1}
        if dup:
            raise ValueError(f"규칙 id 중복: {sorted(dup)}")
        codes = {c.code for c in self.coverage_codes}
        for c in self.coverages:
            for k in c.risks:
                if codes and k.coverage_code not in codes:
                    raise ValueError(
                        f"{k.id}: 담보코드 {k.coverage_code} 가 coverage_codes 에 없습니다."
                    )
                for r in k.rules:
                    for s in r.special_conditions:
                        if s.related_rule_id and s.related_rule_id not in ids:
                            raise ValueError(f"{r.id}: 관계 규칙 {s.related_rule_id} 가 없습니다.")
        return self
