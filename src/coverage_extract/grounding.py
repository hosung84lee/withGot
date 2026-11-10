"""사고보장 데이터의 근거 검증 (LLM 없이 규칙으로).

추출된 규칙·보상 제외마다 다음을 확인하고, 모두 맞으면 status="confirmed", 하나라도 틀리면
"needs_review" 로 둡니다. confirmed 는 '원문에 근거가 있다'는 뜻이고, 업무 판단까지 끝났다는
뜻은 아닙니다.

- SOURCE_NOT_FOUND: source 의 약관·보장종목·조가 구조화 결과에 없음 (error)
- PARAGRAPH_NOT_FOUND: source 의 항이 그 조에 없음 (warning)
- QUOTE_NOT_FOUND: source.quote 가 그 조 원문에 없음 (공백·따옴표 차이는 무시) (warning)
- NUMBER_NOT_FOUND: 규칙의 숫자(보상률 80%, 한도 20만원, 180일 …)가 근거 조들의 원문에 없음 (warning)
"""

import re
from typing import Literal

from pydantic import BaseModel

from schema.coverage import BenefitRule, Exclusion, Product, SourceRef
from schema.terms import Appendix, Article, TermsDocument

_NOISE = re.compile(r"[\s\"'“”‘’`·∙ㆍ･]+")
_UNITS = {
    "억": 100_000_000,
    "천만": 10_000_000,
    "백만": 1_000_000,
    "십만": 100_000,
    "만": 10_000,
    "천": 1_000,
    "": 1,
}
_AMOUNT = re.compile(r"(\d+(?:,\d{3})*)(억|천만|백만|십만|만|천)?원")
_PERCENT = re.compile(r"(\d+(?:\.\d+)?)%")
_DAYS = re.compile(r"(\d+)일")
_YEARS = re.compile(r"(\d+)년(?:이내|이후|초과|간|동안|이 ?지|이되|단위)")  # 기간으로 쓰인 'N년'
_APPENDIX_NO = re.compile(r"별표\s*(\d+)")
_COUNT = re.compile(r"(\d+)회")


class GroundingIssue(BaseModel):
    severity: Literal["error", "warning"]
    code: str
    target: str  # 규칙·보상 제외 id
    message: str


class GroundingReport(BaseModel):
    product: Product
    issues: list[GroundingIssue]

    @property
    def confirmed(self) -> int:
        items = [*self.product.rules(), *self.product.exclusions()]
        return sum(1 for x in items if x.status == "confirmed")

    @property
    def needs_review(self) -> int:
        items = [*self.product.rules(), *self.product.exclusions()]
        return sum(1 for x in items if x.status == "needs_review")


def squash(text: str) -> str:
    """공백·줄바꿈·따옴표·가운뎃점 차이를 무시하고 비교하기 위한 정규화."""
    return _NOISE.sub("", text)


def numbers_in(text: str) -> dict[str, set[float]]:
    """원문 속 숫자를 단위별로 뽑음. '5천\\n만원' 처럼 줄바꿈으로 끊긴 것도 붙여서 읽음."""
    t = squash(text)
    return {
        "amount": {
            float(m.group(1).replace(",", "")) * _UNITS[m.group(2) or ""]
            for m in _AMOUNT.finditer(t)
        },
        "percent": {float(m.group(1)) for m in _PERCENT.finditer(t)},
        # 'N년'(기간)은 N×365일로도 읽음: '계약일부터 1년 이내' ↔ 감액기간 365일
        "days": {float(m.group(1)) for m in _DAYS.finditer(t)}
        | {float(m.group(1)) * 365 for m in _YEARS.finditer(t)},
        "count": {float(m.group(1)) for m in _COUNT.finditer(t)},
    }


def _ratio_percent(numerator: float, denominator: float) -> float:
    return round(numerator / denominator * 100, 4)


def expected_numbers(rule: BenefitRule) -> list[tuple[str, float, str]]:
    """규칙에서 원문으로 확인할 숫자: (단위, 값, 무엇)."""
    out: list[tuple[str, float, str]] = []
    b, c = rule.benefit, rule.conditions
    if b.ratio:
        out.append(("percent", _ratio_percent(b.ratio.numerator, b.ratio.denominator), "보상률"))
    if b.fixed_amount:
        out.append(("amount", b.fixed_amount, "지급금액"))
    if b.copay_cap_annual:
        out.append(("amount", b.copay_cap_annual, "자기부담 연간 상한"))
    if b.deductible:
        out += [("amount", a, "공제금액") for a in b.deductible.amounts]
        out += [
            ("percent", _ratio_percent(r.numerator, r.denominator), "공제비율")
            for r in b.deductible.ratios
        ]
    if c.limit:
        out += [("amount", a.amount, f"한도({a.per})") for a in c.limit.amounts]
    if c.extension:
        out.append(("days", c.extension.days, "연장 보상 일수"))
        if c.extension.max_visits:
            out.append(("count", c.extension.max_visits, "연장 보상 통원 횟수"))
    if c.exemption_days:
        out.append(("days", c.exemption_days, "면책기간"))
    if c.reduction:
        out.append(("days", c.reduction.days, "감액기간"))
    return out


def _part_index(doc: TermsDocument, part: str) -> int | None | Literal[False]:
    """SourceRef.part → doc.parts 위치. 약관 제목 줄이 없는 문서면 None, 못 찾으면 False."""
    if not doc.parts:
        return None
    want = squash(part)
    exact = [i for i, p in enumerate(doc.parts) if squash(p.title) == want]
    if exact:
        return exact[0]
    loose = [
        i
        for i, p in enumerate(doc.parts)
        if want and (want in squash(p.title) or squash(p.title) in want)
    ]
    return loose[0] if len(loose) == 1 else False


def find_article(doc: TermsDocument, src: SourceRef) -> Article | None:
    if not src.article:
        return None
    part = _part_index(doc, src.part)
    if part is False:
        return None
    label = squash(src.article)
    cands = [a for a in doc.body_articles if a.part == part and squash(a.label) == label]
    if src.section:
        sec = squash(src.section)
        same = [a for a in cands if a.section and squash(a.section) == sec]
        cands = same or [a for a in cands if a.section is None]
    return cands[0] if cands else None


def find_appendix(doc: TermsDocument, src: SourceRef) -> Appendix | None:
    """source 의 별표. 별표 번호는 약관마다 1부터라, source.part 약관 범위(줄 번호) 안에서 찾음.
    '별표1' 이 '별표 10' 에 맞지 않도록 번호는 정확히 비교."""
    if not src.appendix:
        return None
    pool = doc.appendices
    part = _part_index(doc, src.part)
    if part is False:
        return None
    if part is not None:
        start = doc.parts[part].line
        end = doc.parts[part + 1].line if part + 1 < len(doc.parts) else float("inf")
        pool = [x for x in pool if start <= x.line < end]
    m = _APPENDIX_NO.search(src.appendix)
    if m:
        cands = [x for x in pool if (n := _APPENDIX_NO.match(x.label)) and n.group(1) == m.group(1)]
    else:
        cands = [x for x in pool if squash(src.appendix) in squash(x.label)]
    return cands[0] if cands else None


def _check_source(
    doc: TermsDocument, src: SourceRef, target: str, issues: list[GroundingIssue]
) -> str | None:
    """근거를 찾아 확인하고 그 원문(조 또는 별표)을 돌려줌. 못 찾으면 None."""
    if src.appendix and not src.article:
        x = find_appendix(doc, src)
        if x is None:
            issues.append(
                GroundingIssue(
                    severity="error",
                    code="SOURCE_NOT_FOUND",
                    target=target,
                    message=f"별표를 찾지 못했습니다: {src.part} {src.appendix}",
                )
            )
            return None
        if src.quote and squash(src.quote) not in squash(x.text):
            issues.append(
                GroundingIssue(
                    severity="warning",
                    code="QUOTE_NOT_FOUND",
                    target=target,
                    message=f"인용문이 {x.label[:20]} 원문에 없습니다: '{src.quote[:60]}'",
                )
            )
        return x.text
    a = find_article(doc, src)
    if a is None:
        where = (
            f"{src.part} " + (f"《{src.section}》 " if src.section else "") + (src.article or "")
        )
        issues.append(
            GroundingIssue(
                severity="error",
                code="SOURCE_NOT_FOUND",
                target=target,
                message=f"근거 조를 찾지 못했습니다: {where}",
            )
        )
        return None
    if src.paragraph is not None:
        numbers = {p.number for p in a.paragraphs if p.number}
        if src.paragraph not in numbers and not (src.paragraph == 1 and not numbers):
            issues.append(
                GroundingIssue(
                    severity="warning",
                    code="PARAGRAPH_NOT_FOUND",
                    target=target,
                    message=f"{a.label}에 제{src.paragraph}항이 없습니다.",
                )
            )
    if src.quote and squash(src.quote) not in squash(a.full_text()):
        issues.append(
            GroundingIssue(
                severity="warning",
                code="QUOTE_NOT_FOUND",
                target=target,
                message=f"인용문이 {a.label} 원문에 없습니다: '{src.quote[:60]}'",
            )
        )
    return a.full_text()


def _ground_rule(doc: TermsDocument, rule: BenefitRule, issues: list[GroundingIssue]) -> None:
    before = len(issues)
    found = [_check_source(doc, s, rule.id, issues) for s in [rule.source, *rule.extra_sources]]
    texts = [t for t in found if t is not None]
    # 주 근거 조를 못 찾았으면 숫자는 확인할 수 없음 (SOURCE_NOT_FOUND 만 알림)
    if found[0] is not None:
        have = numbers_in("\n".join(texts))
        for unit, value, what in expected_numbers(rule):
            if float(value) not in have[unit]:
                issues.append(
                    GroundingIssue(
                        severity="warning",
                        code="NUMBER_NOT_FOUND",
                        target=rule.id,
                        message=f"{what} {value:g}({unit})가 근거 조 원문에 없습니다.",
                    )
                )
    rule.status = "confirmed" if len(issues) == before else "needs_review"


def _ground_exclusion(doc: TermsDocument, ex: Exclusion, issues: list[GroundingIssue]) -> None:
    before = len(issues)
    _check_source(doc, ex.source, ex.id, issues)
    ex.status = "confirmed" if len(issues) == before else "needs_review"


def ground_product(product: Product, doc: TermsDocument) -> GroundingReport:
    """규칙·보상 제외의 근거를 원문과 맞춰 보고 status 를 정함. product 는 복사본을 고쳐서 돌려줌."""
    product = product.model_copy(deep=True)
    issues: list[GroundingIssue] = []
    for rule in product.rules():
        _ground_rule(doc, rule, issues)
    for ex in product.exclusions():
        _ground_exclusion(doc, ex, issues)
    for code in product.coverage_codes:
        if code.source:
            _check_source(doc, code.source, code.code, issues)
    return GroundingReport(product=product, issues=issues)
