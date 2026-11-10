"""추출 결과를 정답(사람이 만든 사고보장 JSON)과 비교.

LLM 이 붙이는 id·이름·인용문은 매번 달라서, 규칙은 내용으로 짝을 맞춥니다.
- 짝 맞추는 키: 보장종목, 청구사유(입원·통원 …), 의료비 구분(급여·비급여), 공제 정액, 특수 조건
- 비교하는 값: 보상률, 공제금액(정액·비율·본인부담률), 금액 한도, 자기부담 연간 상한, 연장 보상
보상 제외는 (종류, KCD 범위 또는 설명) 으로 짝을 맞춥니다.
"""

from pydantic import BaseModel

from schema.coverage import BenefitRule, Exclusion, Product, Risk


class CompareResult(BaseModel):
    matched: list[str]  # 값까지 같은 규칙
    different: list[str]  # 짝은 맞는데 값이 다른 규칙 (무엇이 다른지)
    missing: list[str]  # 정답에는 있는데 추출 결과에 없음
    extra: list[str]  # 추출 결과에만 있음

    @property
    def score(self) -> float:
        """정답 규칙 중 값까지 맞힌 비율."""
        total = len(self.matched) + len(self.different) + len(self.missing)
        return len(self.matched) / total if total else 1.0


def _rule_key(risk: Risk, rule: BenefitRule) -> tuple:
    b = rule.benefit
    return (
        risk.section,
        risk.claim_reason,
        b.cost_type,
        tuple(sorted(b.deductible.amounts)) if b.deductible else (),
        tuple(sorted(s.type for s in rule.special_conditions)),
    )


def _rule_values(rule: BenefitRule) -> dict:
    b, c = rule.benefit, rule.conditions
    return {
        "보상률": round(b.ratio.value, 4) if b.ratio else None,
        "공제 정액": sorted(b.deductible.amounts) if b.deductible else [],
        "공제 비율": sorted(round(r.value, 4) for r in b.deductible.ratios) if b.deductible else [],
        "본인부담률 공제": bool(b.deductible and b.deductible.copay_rate),
        "금액 한도": sorted((a.per, a.amount) for a in c.limit.amounts) if c.limit else [],
        "자기부담 연간 상한": b.copay_cap_annual,
        "연장 보상": (c.extension.days, c.extension.max_visits, c.extension.max_visit_days)
        if c.extension
        else None,
    }


def _rules(p: Product) -> dict[tuple, tuple[str, BenefitRule]]:
    out = {}
    for cov in p.coverages:
        for risk in cov.risks:
            for rule in risk.rules:
                out[_rule_key(risk, rule)] = (f"{risk.section or ''} {rule.name}".strip(), rule)
    return out


def _exclusion_key(p: Product, e: Exclusion) -> tuple:
    if e.kind == "kcd" and e.coverage_code:
        code = next((c for c in p.coverage_codes if c.code == e.coverage_code), None)
        if code and code.kcd:
            return (e.section, "kcd", tuple(sorted((k.start, k.end) for k in code.kcd)))
    return (e.section, e.kind, e.description.replace(" ", ""))


def compare_products(extracted: Product, golden: Product) -> CompareResult:
    got, want = _rules(extracted), _rules(golden)
    matched, different, missing = [], [], []
    for key, (name, rule) in want.items():
        if key not in got:
            missing.append(name)
            continue
        a, b = _rule_values(got[key][1]), _rule_values(rule)
        diffs = [f"{k}: {a[k]} (정답 {b[k]})" for k in b if a[k] != b[k]]
        (different if diffs else matched).append(
            f"{name}" + (f" — {'; '.join(diffs)}" if diffs else "")
        )
    extra = [name for key, (name, _) in got.items() if key not in want]

    got_ex = {_exclusion_key(extracted, e): e for e in extracted.exclusions()}
    want_ex = {_exclusion_key(golden, e): e for e in golden.exclusions()}
    for key, e in want_ex.items():
        (matched if key in got_ex else missing).append(f"(제외) {e.description}")
    extra += [f"(제외) {e.description}" for key, e in got_ex.items() if key not in want_ex]
    return CompareResult(matched=matched, different=different, missing=missing, extra=extra)
