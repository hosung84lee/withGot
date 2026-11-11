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


COST_TYPE = {
    "covered": "covered",
    "uncovered": "non_covered",
}  # diagnosis 는 진단 연결로 따로  # 서류 급여 구분 → 스키마 cost_type
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
class Visit:
    """통원 1회 (방문일 하루)의 참고 계산."""

    date: str  # 'MM.DD' 또는 날짜를 모르면 '미상 1'
    covered: int
    deductible: int
    payable: int
    capped: bool = False  # 통원 1회(1일) 한도 적용


@dataclass
class Estimate:
    rule: BenefitRule
    covered: int  # 대상 의료비 (환자 부담)
    deductible: int
    payable: int
    notes: list[str]
    visits: list[Visit] = field(default_factory=list)  # 방문일별 계산 (통원, 날짜가 있는 서류)


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
    if b.type == "fixed" and b.fixed_amount:
        notes.append(f"정액 {_won(b.fixed_amount)}")
    elif b.type == "rate" and b.ratio:
        base = {"sum_insured": "가입금액", "premium_paid": "납입보험료"}.get(b.base, b.base)
        notes.append(f"{base}의 {b.ratio.numerator / b.ratio.denominator:.0%}")
    elif b.ratio:
        notes.append(f"보상률 {b.ratio.numerator / b.ratio.denominator:.0%}")
    if b.deductible:
        parts = [_won(a) for a in b.deductible.amounts]
        parts += [f"{r.numerator / r.denominator:.0%}" for r in b.deductible.ratios]
        notes.append(f"공제 {' 와 '.join(parts)} 중 큰 금액")
    if c.limit:
        for a in c.limit.amounts:
            notes.append(f"한도 {LIMIT_PER.get(a.per, a.per)} {_won(a.amount)}")
        if c.limit.count:
            notes.append(f"{c.limit.count}회 한도")
    if c.occurrence == "first":
        notes.append("최초 1회")
    if c.exemption_days:
        notes.append(f"면책 {c.exemption_days}일")
    if c.reduction:
        r = c.reduction
        notes.append(f"{r.days}일 이내 {r.ratio.numerator / r.ratio.denominator:.0%} 지급")
    if b.copay_cap_annual:
        notes.append(f"자기부담 연간 {_won(b.copay_cap_annual)} 초과분 보상")
    notes += [s.description for s in rule.special_conditions if s.description][:2]
    return notes


# 진단 코드(KCD)만으로 정할 수 없어 서류를 읽고 판단해야 하는 조건 (AI 판단 항목 후보)
JUDGEMENT_TYPES = ("stage_criteria", "excluded_code")


def _judgements(rule: BenefitRule) -> list[str]:
    return [s.description for s in rule.special_conditions if s.type in JUDGEMENT_TYPES]


def _judge_notes(conditions: list[str], stage: str | None) -> list[str]:
    notes = ["판단 필요: " + " / ".join(conditions)]
    notes.append(f"서류의 병기: {stage}" if stage else "서류에서 병기를 찾지 못했습니다.")
    return notes


def _diagnosis_links(claim: Claim, product: Product, section: str | None) -> list[Link]:
    """진단서의 질병코드(KCD) → 진단 보장(claim_reason=diagnosis)의 담보코드 KCD 범위로 연결 (정액형)."""
    codes = {c.code: c for c in product.coverage_codes}
    risks = [
        r
        for cov in product.coverages
        for r in cov.risks
        if r.claim_reason == "diagnosis" and (section is None or r.section in (None, section))
    ]
    if not risks:
        return []
    src_doc = next((d.filename for d in claim.docs if d.kind == "DIAGNOSIS"), "")
    stages = list(dict.fromkeys(d.fields["병기"] for d in claim.docs if d.fields.get("병기")))
    # 진단서가 여러 장이고 병기가 서로 다르면 모두 보여 줌 (어느 쪽이 맞는지는 사람이 확인)
    stage = (
        ("서류마다 다름 → " + " / ".join(stages))
        if len(stages) > 1
        else (stages[0] if stages else None)
    )
    links = []
    for code in claim.kcd:
        item = Item(f"진단 {code}", "diagnosis", 0, 0, src_doc, 0)
        matched = []
        for risk in risks:
            cc = codes.get(risk.coverage_code or "")
            if cc and any(kcd_in(code, k.start, k.end) for k in cc.kcd):
                for rule in risk.rules:
                    judge = _judgements(rule)
                    notes = [cc.name, *_rule_notes(rule)]
                    if judge:  # 진단 코드만으로 정할 수 없는 조건 → 사람·AI 판단
                        notes = [*_judge_notes(judge, stage), *notes]
                    matched.append(
                        Link(item, "check" if judge else "linked", rule=rule, notes=notes)
                    )
        if matched:
            # 담보코드 없이 병기·조직형으로만 정해지는 진단 보장(소액암 등) 중, 이 진단이 속한
            # 담보코드 이름(유방암·갑상선암 …)이 규칙 이름에 나오는 것을 후보로 함께 보여 줌
            names = {
                cc.name.split(" ")[0].split("(")[0]
                for cc in codes.values()
                if any(kcd_in(code, k.start, k.end) for k in cc.kcd)
            }
            candidates = [
                rule
                for risk in risks
                for rule in ([] if risk.coverage_code else risk.rules)
                if _judgements(rule) and any(len(n) >= 2 and n in rule.name for n in names)
            ]
            if candidates:  # 병기에 따라 '암'이 아닌 쪽으로 분류될 수 있음 → 전부 판단 대상
                for link in matched:
                    if link.status == "linked":
                        link.status = "check"
                        link.notes = [
                            "판단 필요: 병기·조직형에 따라 이 보장이 아니라 "
                            + ", ".join(r.name for r in candidates)
                            + " 대상일 수 있습니다.",
                            f"서류의 병기: {stage}"
                            if stage
                            else "서류에서 병기를 찾지 못했습니다.",
                            *link.notes,
                        ]
            links += matched
            links += [
                Link(item, "check", rule=rule, notes=_judge_notes(_judgements(rule), stage))
                for rule in candidates
            ]
        else:
            uncoded = [r for r in risks if not r.coverage_code]
            note = f"진단 {code} 에 맞는 진단 보장(담보코드 KCD)을 찾지 못했습니다."
            if uncoded:
                note += " 담보코드가 없는 진단 보장은 직접 확인하세요: " + ", ".join(
                    r.rules[0].name for r in uncoded if r.rules
                )
            links.append(Link(item, "check", notes=[note]))
    return links


def link_claim(
    claim: Claim,
    product: Product,
    section: str | None = None,
    coverage_id: str | None = None,
) -> CoverageMap:
    """coverage_id 를 주면 그 보장(약관) 안에서만 연결합니다.

    보장종목 이름은 약관마다 겹칠 수 있음 (비중증·중증 비급여 특약 모두 《질병비급여형》).
    section 만 주면 이름이 같은 다른 특약의 규칙이 섞이므로, 화면은 둘 다 넘깁니다.
    """
    full = product
    if coverage_id is not None:
        product = product.model_copy(
            update={"coverages": [c for c in product.coverages if c.id == coverage_id]}
        )
    # 선택한 보장종목 안의 규칙만 봄 (다른 보장종목·특약의 비급여 규칙과 섞지 않음)
    section_rules = [
        r
        for cov in product.coverages
        for risk in cov.risks
        if section is None or risk.section == section
        for r in risk.rules
    ]
    names = [risk.section for cov in full.coverages for risk in cov.risks if risk.section]
    dup = {
        n
        for n in names
        if len({c.id for c in full.coverages for k in c.risks if k.section == n}) > 1
    }
    elsewhere = sorted(
        {
            (f"{risk.section} ({cov.name})" if risk.section in dup else risk.section) or cov.name
            for cov in full.coverages
            for risk in cov.risks
            if (risk.section != section or (coverage_id is not None and cov.id != coverage_id))
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

    links += _diagnosis_links(claim, product, section)
    return CoverageMap(claim, product, links, claim_excl, _estimates(links, claim))


def _md(date: str) -> tuple[int, int]:
    m, d = date.split(".")
    return int(m), int(d)


def _row_dates(item: Item, known: list[str], period_end: str | None) -> tuple[list[str], bool]:
    """세부내역 한 줄(일자 + 일수) → 방문일 목록, 추정 여부.

    '07.06' 1일 → 그날. '07.09~08.06' 9일 → 그 기간의 알려진 방문일 9개 (수가 맞으면 확정).
    알려진 방문일이 더 많으면 고르게 골라 추정, 모자라면 '미상 n' 으로 채웁니다.
    """
    spec, n = item.date or "", max(1, item.days)
    start, _, end = spec.partition("~")
    if "~" not in spec and n == 1:
        return [start], False
    end = end or period_end or "12.31"
    inside = [d for d in known if _md(start) <= _md(d) <= _md(end)]
    if len(inside) == n:
        return inside, False
    if len(inside) > n:
        step = (len(inside) - 1) / (n - 1) if n > 1 else 0
        return [inside[round(i * step)] for i in range(n)], True
    return inside + [f"미상 {spec} #{i + 1}" for i in range(n - len(inside))], True


def _deductible(rule: BenefitRule, covered: int, copay_rate: tuple[int, int] | None) -> int:
    d = rule.benefit.deductible
    assert d is not None
    cands = [float(a) for a in d.amounts]
    cands += [covered * r.numerator / r.denominator for r in d.ratios]
    if d.copay_rate and copay_rate:
        cands.append(covered * copay_rate[0] / copay_rate[1])
    if not cands:
        return 0
    pick = {"max": max, "min": min, "sum": sum}[d.pick]
    return int(pick(cands))


def _visit_estimate(rule: BenefitRule, group: list[Link], claim: Claim, cap) -> Estimate:
    """통원: 방문일마다 공제·한도를 따로 적용 (약관: 통원 1회당 공제, 통원 1회(1일)당 한도)."""
    period_end = claim.period.split("~")[1].strip()[5:] if claim.period else None
    # 방문일: 서류의 방문일 목록 + 세부내역의 일자 (기간 '07.09~08.06' 은 시작일·끝일도 방문일)
    dated = set()
    for link in group:
        start, _, end = (link.item.date or "").partition("~")
        dated |= {d for d in (start, end or (period_end if "~" in link.item.date else "")) if d}
    known = sorted(set(claim.visit_dates) | dated, key=_md)
    per_visit: dict[str, int] = {}
    estimated = False
    for link in group:
        dates, guess = _row_dates(link.item, known, period_end)
        estimated |= guess
        base, extra = divmod(link.item.patient, len(dates))
        for i, day in enumerate(dates):
            per_visit[day] = per_visit.get(day, 0) + base + (1 if i < extra else 0)
    visits = []
    for day in sorted(
        per_visit, key=lambda d: (d.startswith("미상"), _md(d) if "." in d[:5] else d)
    ):
        covered = per_visit[day]
        ded = _deductible(rule, covered, claim.copay_rate)
        pay = max(0, covered - ded)
        capped = bool(cap and pay > cap.amount)
        visits.append(Visit(day, covered, ded, cap.amount if capped else pay, capped))
    notes = [f"방문 {len(visits)}회를 각각 계산 (통원 공제는 1회마다 적용)"]
    if estimated:
        notes.append(
            "일부 방문일은 서류에 날짜가 없어 추정했습니다. 방문일이 달라지면 금액이 바뀝니다."
        )
    d = rule.benefit.deductible
    if d and d.copay_rate:
        if claim.copay_rate:
            rate = claim.copay_rate[0] / claim.copay_rate[1]
            notes.append(f"건강보험 본인부담률 {rate:.1%} (영수증의 본인부담금 ÷ 급여 총액) 반영")
        else:
            notes.append("본인부담률 기준 공제는 서류에 본인부담률이 없어 빼고 계산")
    if any(v.capped for v in visits):
        unit = "1회" if cap.per == "visit" else "1일"
        notes.append(f"통원 {unit} 한도 {_won(cap.amount)} 적용 {sum(v.capped for v in visits)}회")
    covered, payable = sum(v.covered for v in visits), sum(v.payable for v in visits)
    # 요약의 공제는 실제로 빠진 금액 (대상 − 지급). 방문별 공제금액은 visits 에
    return Estimate(rule, covered, covered - payable, payable, notes, visits)


def _estimates(links: list[Link], claim: Claim) -> list[Estimate]:
    """규칙별 참고 계산. 통원은 날짜가 있는 서류면 방문일별로, 아니면 진료 건 1회로 계산."""
    out = []
    groups: dict[str, list[Link]] = {}
    for link in links:
        if link.status == "linked" and link.rule and link.item.benefit != "diagnosis":
            groups.setdefault(link.rule.id, []).append(link)
    for group in groups.values():
        rule = group[0].rule
        assert rule is not None
        b = rule.benefit
        cap = next(
            (
                a
                for a in (rule.conditions.limit.amounts if rule.conditions.limit else [])
                if a.per in ("visit", "day")
            ),
            None,
        )
        if b.deductible and claim.setting == "outpatient" and all(link.item.date for link in group):
            out.append(_visit_estimate(rule, group, claim, cap))
            continue
        covered = sum(link.item.patient for link in group)
        notes = []
        if b.deductible:
            ded = _deductible(rule, covered, claim.copay_rate)
            payable = max(0, covered - ded)
            if b.deductible.copay_rate and not claim.copay_rate:
                notes.append("본인부담률 기준 공제는 서류에 본인부담률이 없어 빼고 계산")
        else:
            ratio = b.ratio.numerator / b.ratio.denominator if b.ratio else 1.0
            ded = round(covered * (1 - ratio))
            payable = covered - ded
            if b.copay_cap_annual:
                notes.append(
                    f"자기부담 연간 {_won(b.copay_cap_annual)} 상한은 연간 누계로 따로 확인"
                )
        # 통원 한도: 약관에 따라 '1회당'(급여) 또는 '1일당'(비급여). 서류 한 건 = 통원 1회·1일로 봄
        if cap and payable > cap.amount:
            unit = "1회" if cap.per == "visit" else "1일"
            notes.append(f"통원 {unit} 한도 {_won(cap.amount)} 적용")
            payable = cap.amount
        out.append(Estimate(rule, covered, ded, payable, notes))
    return out
