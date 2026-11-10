"""사고보장 데이터(schema.coverage.Product) → 보장 JSON(coverage.json) 목록.

정답 데이터·AI 추출 캐시처럼 이미 Product 로 만든 데이터를 새 스키마 모양으로 옮깁니다 (LLM 없음).
Product 에 없는 정보(코드로 못 가르는 분류질병 판정, 연금 등)는 비워 둡니다.
"""

import re

from schema.coverage import BenefitRule, Coverage, Product, Risk, SourceRef

from .kcd import range_to_patterns

CLAIM_REASON = {
    "diagnosis": "진단",
    "surgery": "수술",
    "hospitalization": "입원",
    "outpatient": "통원",
    "death": "사망",
    "disability": "장해",
    "other": "판단불가",
}
REASON_CODE = {
    "diagnosis": "DX",
    "surgery": "SG",
    "hospitalization": "HOSP",
    "outpatient": "OUT",
    "death": "DTH",
    "disability": "DIS",
    "other": "ETC",
}
SECTION_CODE = {
    "질병급여형": "DIS-COV",
    "상해급여형": "INJ-COV",
    "질병비급여형": "DIS-NONCOV",
    "상해비급여형": "INJ-NONCOV",
    "3대비급여형": "TOP3",
    "비급여자기공명영상진단형": "MRI",
}
PRODUCT_KEYWORDS = [("실손", "IND"), ("암", "CA"), ("종신", "WL"), ("간병", "LTC")]
INSURER_CODE = {"삼성생명": "SL"}


def product_code(name: str) -> str:
    kind = next((code for word, code in PRODUCT_KEYWORDS if word in name), "P")
    digits = re.search(r"\((\d{4})\)", name)
    return kind + (digits.group(1) if digits else "")


def _source(src: SourceRef | None) -> dict | None:
    if not src:
        return None
    return {
        "policy_name": src.part,
        "article": src.article,
        "paragraph": src.paragraph,
        "item": src.item,
        "appendix": src.appendix,
        "quote": src.quote,
    }


def _ratio(r) -> float | None:
    return round(r.numerator / r.denominator, 4) if r else None


def _kcd_patterns(product: Product, code: str | None) -> list[str]:
    cc = next((c for c in product.coverage_codes if c.code == code), None)
    if not cc:
        return []
    out = []
    for k in cc.kcd:
        try:
            out += range_to_patterns(k.start, k.end)
        except ValueError:
            continue
    return out


def _policy(product: Product, cov: Coverage, section: str | None) -> dict:
    name = cov.name
    renewal = (
        "갱신형"
        if "갱신형" in name and "비갱신" not in name
        else ("비갱신형" if "비갱신" in name else None)
    )
    return {
        "product_name": product.name,
        "policy_name": name,
        "policy_kind": "주계약" if cov.kind == "main" else "보장특약",
        "section": section,
        "renewal": renewal,
        "policy_version": product.version or None,
    }


def _facility_group(text: str | None) -> str | None:
    if not text:
        return None
    if "종합병원" in text and "제외" not in text:
        return "종합병원·상급종합병원"
    if "의원" in text or "약국" in text:
        return "의원·약국 등"
    if "병원" in text:
        return "병원"
    return None


def _indemnity_rule(risk: Risk, rule: BenefitRule) -> dict:
    b, c = rule.benefit, rule.conditions
    amounts = c.limit.amounts if c.limit else []

    def limit(per: str) -> float | None:
        return next((a.amount for a in amounts if a.per == per), None)

    category = {
        "covered": "급여",
        "non_covered": "비급여",
        "room_difference": "상급병실료차액",
    }.get(b.cost_type or "", "판단불가")
    ded = b.deductible
    facility = _facility_group(c.facility)
    return {
        "care_type": {"hospitalization": "입원", "outpatient": "통원"}.get(
            risk.claim_reason, "판단불가"
        ),
        "benefit_category": category,
        "facility_group": facility,
        "covered_ratio": _ratio(b.ratio),
        "min_deductible_amounts": (
            {(facility or "회당"): float(max(ded.amounts))} if ded and ded.amounts else None
        ),
        "deductible_ratio": _ratio(ded.ratios[0]) if ded and ded.ratios else None,
        "deductible_copay_rate": ded.copay_rate if ded else None,
        "annual_limit_amount": limit("year"),
        "per_visit_limit_amount": limit("visit"),
        "per_admission_limit_amount": limit("stay"),
        "daily_limit_amount": limit("day") or limit("daily_average"),
        "annual_visit_limit": None,
        "annual_copay_cap_amount": b.copay_cap_annual,
        "source": _source(rule.source),
    }


def _exclusions(product: Product, cov: Coverage, section: str | None) -> list[dict]:
    kind = {"kcd": "질병", "cost_item": "비용항목", "cause": "원인"}
    out = []
    for e in cov.exclusions:
        if section and e.section not in (None, section):
            continue
        out.append(
            {
                "kind": kind.get(e.kind, "판단불가"),
                "description": e.description,
                "kcd_code_patterns": _kcd_patterns(product, e.coverage_code),
                "exception": e.exception,
                "source": _source(e.source),
            }
        )
    return out


def _benefit(rule: BenefitRule, code: str) -> dict:
    b, c = rule.benefit, rule.conditions
    amount = None
    if b.type == "rate":
        base = {"sum_insured": "보험가입금액"}.get(b.base, None)
        amount = {"amount_type": "가입금액비율", "base": base, "ratio": _ratio(b.ratio)}
    elif b.type == "fixed":
        amount = {"amount_type": "정액", "fixed_amount": b.fixed_amount}
    limit = None
    if c.occurrence == "first":
        limit = {"count": 1, "per": "보험기간"}
    elif c.limit and c.limit.count:
        limit = {"count": c.limit.count, "per": "보험기간"}
    return {
        "benefit_code": code,
        "benefit_name": rule.name,
        "benefit_description": "; ".join(s.description for s in rule.special_conditions),
        "calc_tool_name": "calc_fixed_ratio_benefit" if b.type == "rate" else "calc_fixed_benefit",
        "amount": amount,
        "payment_limit": limit,
        "source": _source(rule.source),
    }


def product_to_items(product: Product) -> list[dict]:
    """Product → 보장 JSON 목록. 실손은 (약관 × 보장종목)마다 1개, 정액형은 위험(risk)마다 1개."""
    insurer = INSURER_CODE.get(product.insurer, "XX")
    pcode = product_code(product.coverages[0].name if product.coverages else product.name)
    items: list[dict] = []
    for ci, cov in enumerate(product.coverages):
        policy_code = "MAIN" if cov.kind == "main" else f"R{ci}"
        indemnity: dict[str | None, list[tuple[Risk, BenefitRule]]] = {}
        for ri, risk in enumerate(cov.risks):
            actual = [r for r in risk.rules if r.benefit.type == "actual_cost"]
            if actual:
                indemnity.setdefault(risk.section, []).extend((risk, r) for r in actual)
            fixed = [r for r in risk.rules if r.benefit.type != "actual_cost"]
            if not fixed:
                continue
            base = f"{insurer}-{pcode}-{policy_code}-{REASON_CODE[risk.claim_reason]}{ri + 1}"
            first = fixed[0]
            c = first.conditions
            items.append(
                {
                    "coverage_id": base,
                    "coverage_name": first.name if len(fixed) == 1 else f"{first.name} 외",
                    "insured_role": "주피보험자"
                    if first.insured_role == "primary"
                    else "종피보험자",
                    "claim_reason": CLAIM_REASON[risk.claim_reason],
                    "policy": _policy(product, cov, risk.section),
                    "kcd_code_patterns": _kcd_patterns(product, risk.coverage_code),
                    "contract_exemption_days": c.exemption_days,
                    "coverage_start": (
                        {"basis": "최초계약일", "waiting_days": c.exemption_days}
                        if c.exemption_days
                        else None
                    ),
                    "reduction_periods": (
                        [
                            {
                                "basis": "최초계약일",
                                "until_days": c.reduction.days,
                                "ratio": _ratio(c.reduction.ratio),
                                "applies_to_renewal": False,
                            }
                        ]
                        if c.reduction
                        else []
                    ),
                    "indemnity": None,
                    "admission": None,
                    "benefits": [_benefit(r, f"{base}-B{k + 1}") for k, r in enumerate(fixed)],
                    "exclusions": [],
                    "pgm_review_items": [],
                    "ai_review_items": [],
                    "source": _source(first.source),
                }
            )
        for section, pairs in indemnity.items():
            scode = SECTION_CODE.get(section or "", "ALL")
            rid = f"{insurer}-{pcode}-{policy_code}-{scode}"
            no_hi = next(
                (
                    _ratio(r.benefit.ratio)
                    for _, r in pairs
                    if any(s.type == "no_health_insurance" for s in r.special_conditions)
                ),
                None,
            )
            rules = [
                _indemnity_rule(risk, r)
                for risk, r in pairs
                if not any(s.type == "no_health_insurance" for s in r.special_conditions)
            ]
            year = next((x["annual_limit_amount"] for x in rules if x["annual_limit_amount"]), None)
            ext = next((r.conditions.extension for _, r in pairs if r.conditions.extension), None)
            items.append(
                {
                    "coverage_id": rid,
                    "coverage_name": f"{cov.name} 《{section}》" if section else cov.name,
                    "insured_role": "주피보험자",
                    "claim_reason": "의료비",
                    "policy": _policy(product, cov, section),
                    "kcd_code_patterns": [],
                    "contract_exemption_days": None,
                    "indemnity": {
                        "generation": "판단불가",
                        "special_case_scope": None,
                        "annual_limit_amount": year,
                        "extension_after_termination": (
                            {
                                "days": ext.days,
                                "max_outpatient_visits": ext.max_visits,
                                "max_outpatient_days": ext.max_visit_days,
                            }
                            if ext
                            else None
                        ),
                        "no_health_insurance_ratio": no_hi,
                        "rules": rules,
                    },
                    "admission": None,
                    "benefits": [
                        {
                            "benefit_code": f"{rid}-B1",
                            "benefit_name": f"실손의료비 {section or ''}".strip(),
                            "benefit_description": ", ".join(r.name for _, r in pairs),
                            "calc_tool_name": "calc_indemnity",
                            "amount": {"amount_type": "실손"},
                        }
                    ],
                    "exclusions": _exclusions(product, cov, section),
                    "pgm_review_items": [],
                    "ai_review_items": [],
                    "source": _source(pairs[0][1].source),
                }
            )
    return items
