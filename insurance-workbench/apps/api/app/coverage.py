"""Synthetic coverage candidates. No clinical or insurance payment determination."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Money = Annotated[int, Field(strict=True, ge=0, le=100_000_000)]
Enrollment = Literal["enrolled", "not_enrolled", "unknown"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    standard: Enrollment = "unknown"
    mri: Enrollment = "unknown"
    injection: Enrollment = "unknown"


class Treatment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: Annotated[int, Field(strict=True, ge=1, le=100)]
    kind: Literal["consultation", "blood_test", "mri", "injection"]
    benefit: Literal["covered", "uncovered", "unknown"]


class TreatmentWithCosts(Treatment):
    """Accept the original request shape from existing callers."""

    total_won: Money
    patient_won: Money

    @model_validator(mode="after")
    def check_cost(self):
        if self.patient_won > self.total_won:
            raise ValueError("invalid_cost")
        return self


def coverage_for(item: Treatment) -> Literal["standard", "mri", "injection"]:
    if item.benefit != "covered" and item.kind in ("mri", "injection"):
        return item.kind
    return "standard"


class CoverageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_version: Literal["synthetic-v1"]
    contract: Contract
    items: Annotated[list[Treatment | TreatmentWithCosts], Field(min_length=1, max_length=100)]

    @model_validator(mode="after")
    def check_items(self):
        if len({item.item_id for item in self.items}) != len(self.items):
            raise ValueError("duplicate_item")
        required = {coverage_for(item) for item in self.items if item.benefit != "unknown"}
        if not required.issubset(self.contract.model_fields_set):
            raise ValueError("missing_enrollment")
        return self


class Candidate(BaseModel):
    item_id: int
    coverage: Literal["standard", "mri", "injection"]
    status: Literal["candidate", "missing_information", "not_enrolled"]
    checks: list[str]


class CoverageResponse(BaseModel):
    rule_version: Literal["synthetic-v1"] = "synthetic-v1"
    synthetic: Literal[True] = True
    items: list[Candidate]


def coverage_candidates(request: CoverageRequest) -> CoverageResponse:
    candidates = []
    for item in request.items:
        coverage = coverage_for(item)
        enrollment = getattr(request.contract, coverage)
        status = "candidate"
        checks = ["공제·한도와 실제 적용 약관 확인"]
        if item.benefit == "unknown":
            status = "missing_information"
            checks = ["급여 구분 확인 후 적용 가능한 담보 확인"]
        elif enrollment == "not_enrolled":
            status = "not_enrolled"
            checks = ["사용자가 선택한 가상 계약에서 해당 담보 미가입"]
        elif enrollment == "unknown":
            status = "missing_information"
            checks = ["담보 가입 여부와 급여 구분 확인"]
        elif item.benefit == "uncovered":
            status = "missing_information"
            checks = ["치료 목적과 해당 특약의 실제 적용 조건 확인"]
        candidates.append(
            Candidate(item_id=item.item_id, coverage=coverage, status=status, checks=checks)
        )
    return CoverageResponse(items=candidates)
