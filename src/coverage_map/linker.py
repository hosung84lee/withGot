"""청구 건의 치료 항목을 약관 보장 규칙(Product)과 연결.

연결은 규칙 데이터(사고보장 스키마)만 보고 하며 LLM 은 쓰지 않습니다.
금액은 '참고 계산' 이며 보험금 지급 판정이 아닙니다.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from schema.coverage import BenefitRule, Exclusion, Product, Risk, SourceRef

from .documents import Claim, Item

DEFAULT_PRODUCT = Path(__file__).resolve().parent / "products" / "silson_2605_disease_covered.json"

# 상태: 연결됨 / 확인 필요 / 이 약관에서 보상 안 함 / 보상 제외
STATUS_LABEL = {
    "linked": "보장 연결",
    "check": "확인 필요",
    "not_covered": "이 약관 보상 대상 아님",
    "excluded": "보상 제외",
}


COST_TYPE = {"covered": "covered", "uncovered": "non_covered"}  # 서류 급여 구분 → 스키마 cost_type
LIMIT_PER = {
    "visit": "통원 1회당",
    "year": "연간",
    "day": "1일당",
    "stay": "1회 입원당",
    "daily_average": "1일 평균",
    "event": "사고 1건당",
}


@dataclass
class Link:
    item: Item
    status: str
    rule: BenefitRule | None = None
    exclusion: Exclusion | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def sources(self) -> list[SourceRef]:
        if self.exclusion:
            return [self.exclusion.source]
        if self.rule:
            return [self.rule.source, *self.rule.extra_sources]
        return []


@dataclass
class Estimate:
    rule: BenefitRule
    covered: int  # 대상 의료비 (환자 부담)
    deductible: int
    payable: int
    notes: list[str]


@dataclass
class CoverageMap:
    claim: Claim
    product: Product
    links: list[Link]
    claim_exclusions: list[tuple[str, Exclusion]]  # (KCD, 제외)
    estimates: list[Estimate]


def load_product(path: Path = DEFAULT_PRODUCT) -> Product:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return Product.model_validate(data.get("product", data))


def article_label(src: SourceRef) -> str:
    circled = "①②③④⑤⑥⑦⑧⑨⑩"
    label = src.article or src.appendix or "?"
    if src.paragraph and 1 <= src.paragraph <= 10:
        label += circled[src.paragraph - 1]
    return label


def _kcd_key(code: str) -> str:
    return code.replace(".", "").upper()


def kcd_in(code: str, start: str, end: str) -> bool:
    """C50.9 가 C00~C97 안인지. 범위 끝은 하위 코드까지 포함 (N39.4 ⊂ N39.4x)."""
    c, s, e = _kcd_key(code), _kcd_key(start), _kcd_key(end)
    return c[: len(s)] >= s and c[: len(e)] <= e


_KCD_RANGE = re.compile(r"([A-Z]\d{2}(?:\.\d{1,2})?)(?:\s*[~∼-]\s*([A-Z]\d{2}(?:\.\d{1,2})?))?")


def in_exception(code: str, exception: str) -> bool:
    """제외의 예외 문구 첫 문장(조건 없는 예외)에 나온 KCD 범위에 code 가 드는지.

    '가입 당시 태아면 …' 같은 조건부 예외(둘째 문장부터)는 보지 않음.
    """
    first = re.split(r"[.。]\s", exception, maxsplit=1)[0]
    return any(kcd_in(code, s, e or s) for s, e in _KCD_RANGE.findall(first))


def _risks(product: Product, section: str | None, reason: str) -> list[Risk]:
    return [
        r
        for cov in product.coverages
        for r in cov.risks
        if r.claim_reason == reason and (section is None or r.section == section)
    ]


def _facility_rule(
    rules: list[BenefitRule], ftype: str | None, pharmacy: bool
) -> BenefitRule | None:
    """통원 규칙 중 의료기관 종류에 맞는 것."""
    if len(rules) == 1:
        return rules[0]
    want = "약국" if pharmacy and ftype in (None, "의원", "약국") else ftype
    keys = {
        "상급종합병원": ("상급종합병원",),
        "종합병원": ("종합병원·", "종합병원의"),
        "의원": ("의원",),
        "약국": ("약국",),
    }.get(want or "", ())
    for r in rules:
        fac = r.conditions.facility or ""
        if keys and any(k in fac for k in keys) and not (want == "종합병원" and "제외" in fac):
            return r
    return None


def _won(n: float) -> str:
    return f"{int(n):,}원"


def _rule_notes(rule: BenefitRule) -> list[str]:
    b, c = rule.benefit, rule.conditions
    notes = []
    if b.ratio:
        notes.append(f"보상률 {b.ratio.numerator / b.ratio.denominator:.0%}")
    if b.deductible:
        parts = [_won(a) for a in b.deductible.amounts]
        parts += [f"{r.numerator / r.denominator:.0%}" for r in b.deductible.ratios]
        notes.append(f"공제 {' 와 '.join(parts)} 중 큰 금액")
    if c.limit:
        for a in c.limit.amounts:
            notes.append(f"한도 {LIMIT_PER.get(a.per, a.per)} {_won(a.amount)}")
    if b.copay_cap_annual:
        notes.append(f"자기부담 연간 {_won(b.copay_cap_annual)} 초과분 보상")
    return notes


def link_claim(claim: Claim, product: Product, section: str | None = None) -> CoverageMap:
    # 선택한 보장종목 안의 규칙만 봄 (다른 보장종목·특약의 비급여 규칙과 섞지 않음)
    section_rules = [
        r
        for cov in product.coverages
        for risk in cov.risks
        if section is None or risk.section == section
        for r in risk.rules
    ]
    elsewhere = sorted(
        {
            risk.section or cov.name
            for cov in product.coverages
            for risk in cov.risks
            if risk.section != section
            and any(r.benefit.cost_type == "non_covered" for r in risk.rules)
        }
    )
    exclusions = [
        ex
        for cov in product.coverages
        for ex in cov.exclusions
        if section is None or ex.section in (None, section)
    ]
    codes = {c.code: c for c in product.coverage_codes}

    # 진단 코드가 제외 질병에 들면 청구 건 전체가 제외 대상
    claim_excl = []
    for code in claim.kcd:
        for ex in exclusions:
            cc = codes.get(ex.coverage_code or "")
            if ex.kind == "kcd" and cc and any(kcd_in(code, k.start, k.end) for k in cc.kcd):
                claim_excl.append((code, ex))

    covers_uncovered = any(r.benefit.cost_type == "non_covered" for r in section_rules)
    reason = "hospitalization" if claim.setting == "hospitalization" else "outpatient"
    risks = _risks(product, section, reason)
    rules = [r for risk in risks for r in risk.rules]

    links = []
    for item in claim.items:
        cost_ex = next(
            (e for e in exclusions if e.kind == "cost_item" and e.description in item.name), None
        )
        if cost_ex:
            links.append(Link(item, "excluded", exclusion=cost_ex, notes=[cost_ex.description]))
            continue
        if item.benefit == "unknown":
            links.append(
                Link(item, "check", notes=["급여·비급여 구분을 확인해야 연결할 수 있습니다."])
            )
            continue
        if item.benefit == "uncovered" and not covers_uncovered:
            links.append(
                Link(
                    item,
                    "not_covered",
                    notes=[
                        "이 보장종목은 급여 의료비만 보상합니다. "
                        + (
                            f"비급여는 {', '.join(elsewhere)} 에서 확인하세요."
                            if elsewhere
                            else "비급여는 비급여 특약에서 확인하세요."
                        )
                    ],
                )
            )
            continue
        want = COST_TYPE[item.benefit]
        candidates = [r for r in rules if r.benefit.cost_type in (None, want)]
        rule = (
            _facility_rule(candidates, claim.facility_type, item.pharmacy)
            if reason == "outpatient"
            else (candidates[0] if candidates else None)
        )
        if rule is None:
            note = (
                f"의료기관 종류({claim.facility_type or '알 수 없음'})에 맞는 통원 규칙을 고르지 못했습니다."
                if candidates
                else "이 약관에서 맞는 보장 규칙을 찾지 못했습니다."
            )
            links.append(Link(item, "check", notes=[note]))
            continue
        if claim_excl:
            code, ex = claim_excl[0]
            if item.benefit == "covered" and in_exception(code, ex.exception):
                # 예: F32 는 정신 및 행동장애(F04~F99) 제외지만 F30~F39 요양급여는 보상 예외
                note = f"진단 {code} 는 「{ex.description}」 제외의 예외(보상)에 해당할 수 있습니다: {ex.exception}"
                links.append(Link(item, "check", rule=rule, exclusion=ex, notes=[note]))
                continue
            note = f"진단 {code} → {ex.description} (보상 제외)"
            if ex.exception:
                note += f". 예외: {ex.exception}"
            links.append(Link(item, "excluded", rule=rule, exclusion=ex, notes=[note]))
            continue
        links.append(Link(item, "linked", rule=rule, notes=_rule_notes(rule)))

    return CoverageMap(claim, product, links, claim_excl, _estimates(links))


def _estimates(links: list[Link]) -> list[Estimate]:
    """규칙별 참고 계산 (한 번의 진료 건 기준)."""
    out = []
    groups: dict[str, list[Link]] = {}
    for link in links:
        if link.status == "linked" and link.rule:
            groups.setdefault(link.rule.id, []).append(link)
    for group in groups.values():
        rule = group[0].rule
        assert rule is not None
        b = rule.benefit
        covered = sum(link.item.patient for link in group)
        notes = []
        if b.deductible:
            cands = list(b.deductible.amounts)
            cands += [covered * r.numerator / r.denominator for r in b.deductible.ratios]
            ded = int(max(cands) if b.deductible.pick == "max" else min(cands)) if cands else 0
            payable = max(0, covered - ded)
            if b.deductible.copay_rate:
                notes.append("본인부담률 기준 공제는 서류에 본인부담률이 없어 빼고 계산")
        else:
            ratio = b.ratio.numerator / b.ratio.denominator if b.ratio else 1.0
            ded = round(covered * (1 - ratio))
            payable = covered - ded
            if b.copay_cap_annual:
                notes.append(
                    f"자기부담 연간 {_won(b.copay_cap_annual)} 상한은 연간 누계로 따로 확인"
                )
        visit = next(
            (
                a.amount
                for a in (rule.conditions.limit.amounts if rule.conditions.limit else [])
                if a.per == "visit"
            ),
            None,
        )
        if visit and payable > visit:
            notes.append(f"통원 1회 한도 {_won(visit)} 적용")
            payable = visit
        out.append(Estimate(rule, covered, ded, payable, notes))
    return out
