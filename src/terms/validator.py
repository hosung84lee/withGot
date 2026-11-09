"""약관 검증.

1) validate_structure: 구조화 결과 자체의 정합성 (번호 누락·중복, 끊어진 조항 인용 등)
2) validate_analysis:  AI 분석 결과가 원문에 근거하는지 (없는 조 인용, 원문에 없는 인용구 등)

둘 다 LLM 없이 규칙으로 판단하므로 결과가 매번 같습니다.
"""

import re
from collections import Counter, defaultdict

from schema.terms import (
    CLAUSE_CATEGORIES,
    HEADING_LEVEL,
    UNFAIR_TYPES,
    Article,
    Item,
    TermsAnalysis,
    TermsDocument,
    ValidationIssue,
    article_label,
)

_MOK_ORDER = "가나다라마바사아자차카타파하"


def _issue(severity, code, message, article: Article | None = None, **kw) -> ValidationIssue:
    return ValidationIssue(
        severity=severity,
        code=code,
        message=message,
        article=article.label if article else kw.pop("label", None),
        line=article.line if article else kw.pop("line", None),
        **kw,
    )


# ---------------------------------------------------------------- 구조 검증


def validate_structure(doc: TermsDocument) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if not doc.articles:
        return [
            _issue(
                "error",
                "NO_ARTICLES",
                "조(제N조) 를 하나도 찾지 못했습니다. 약관 원문인지, 텍스트가 추출되는 PDF 인지 확인하세요.",
            )
        ]

    issues += _check_headings(doc)

    for i, part in enumerate(doc.parts):
        if not any(a.part == i for a in doc.articles):
            issues.append(
                _issue(
                    "warning",
                    "PART_WITHOUT_ARTICLES",
                    f"'{part.title}'에서 조를 찾지 못했습니다. "
                    "조 표기가 '제N조', '제N-M조' 가 아닌지 확인하세요.",
                    label=part.title,
                    line=part.line,
                )
            )

    # 조 번호는 약관(주계약·특약)마다, 그 안에서 본문·부칙마다, 편-조 번호면 편마다 따로 매깁니다
    groups: dict[tuple[int, int, int], list[Article]] = defaultdict(list)
    for a in doc.articles:
        key = (a.part if a.part is not None else -1, a.addendum or 0, a.volume or 0)
        groups[key].append(a)
    for (part, addendum, volume), arts in groups.items():
        prefix = f"[{doc.parts[part].title}] " if part >= 0 and len(doc.parts) > 1 else ""
        issues += _check_article_numbers(
            arts, prefix + ("부칙 " if addendum else ""), volume or None
        )

    for a in doc.articles:
        issues += _check_article(a)
    issues += _check_references(doc)

    if not doc.addenda:
        issues.append(_issue("info", "NO_ADDENDUM", "부칙(시행일 등)이 없습니다."))
    return issues


def _check_headings(doc: TermsDocument) -> list[ValidationIssue]:
    """같은 종류 제목의 번호가 이어지는지.

    하위 제목은 상위 제목이 바뀌면 1부터 다시 매기거나(제1장 제1절, 제2장 제1절),
    문서 전체에서 이어 매깁니다(제1장 제1절, 제2장 제2절). 둘 다 정상으로 봅니다.
    """
    issues = []
    local: dict[str, int] = {}  # 현재 상위 제목 아래 마지막 번호
    total: dict[str, int] = {}  # 문서 전체 마지막 번호
    part = None
    for h in doc.headings:
        if h.part != part:  # 약관(특약)이 바뀌면 번호를 처음부터
            local, total, part = {}, {}, h.part
        level = HEADING_LEVEL[h.kind]
        for kind, lv in HEADING_LEVEL.items():
            if lv > level:
                local.pop(kind, None)
        prev, prev_total = local.get(h.kind, 0), total.get(h.kind, 0)
        if h.number == prev:
            issues.append(
                _issue(
                    "warning",
                    "HEADING_DUPLICATE",
                    f"제{h.number}{h.kind}이 중복됩니다.",
                    label=h.label,
                    line=h.line,
                )
            )
        elif h.number not in (prev + 1, prev_total + 1):
            issues.append(
                _issue(
                    "warning",
                    "HEADING_NUMBER_GAP",
                    f"{h.kind} 번호가 이어지지 않습니다: 제{prev}{h.kind} 다음 제{h.number}{h.kind}",
                    label=h.label,
                    line=h.line,
                )
            )
        local[h.kind] = h.number
        total[h.kind] = max(prev_total, h.number)
    return issues


def _check_article_numbers(
    arts: list[Article], prefix: str, volume: int | None = None
) -> list[ValidationIssue]:
    issues = []

    def lb(n: int) -> str:
        return article_label(n, volume=volume)

    seen = Counter((a.number, a.sub) for a in arts)
    for a in arts:
        if seen[(a.number, a.sub)] > 1:
            issues.append(
                _issue(
                    "error",
                    "ARTICLE_DUPLICATE",
                    f"{a.label}가 {seen[(a.number, a.sub)]}번 나옵니다.",
                    a,
                )
            )
            seen[(a.number, a.sub)] = 0  # 한 번만 보고

    mains = [a for a in arts if a.sub is None]
    expected = 1
    for a in mains:
        if a.number > expected:
            missing = (
                lb(expected) if a.number == expected + 1 else f"{lb(expected)}~{lb(a.number - 1)}"
            )
            issues.append(
                _issue("warning", "ARTICLE_NUMBER_GAP", f"{prefix}{missing}가 없습니다.", a)
            )
        elif a.number < expected - 1:
            issues.append(
                _issue(
                    "warning",
                    "ARTICLE_ORDER",
                    f"{a.label}가 앞 조({lb(expected - 1)})보다 번호가 작습니다.",
                    a,
                )
            )
        expected = max(expected, a.number + 1)

    for a in arts:  # 제N조의M 은 제N조 뒤에 있어야 함
        if a.sub is not None and not any(m.number == a.number for m in mains):
            issues.append(
                _issue(
                    "warning",
                    "ORPHAN_SUB_ARTICLE",
                    f"{a.label}가 있지만 {lb(a.number)}가 없습니다.",
                    a,
                )
            )
    return issues


def _check_article(a: Article) -> list[ValidationIssue]:
    issues = []
    if a.deleted:
        return issues
    if not a.title and not a.addendum:
        issues.append(_issue("info", "MISSING_TITLE", f"{a.label}에 제목이 없습니다.", a))
    if not a.full_text().strip():
        issues.append(_issue("warning", "EMPTY_ARTICLE", f"{a.label}에 본문이 없습니다.", a))

    numbered = [p.number for p in a.paragraphs if p.number is not None]
    if numbered:
        if any(p.number is None for p in a.paragraphs[1:]):
            issues.append(
                _issue(
                    "warning",
                    "MIXED_PARAGRAPHS",
                    f"{a.label}에 번호 있는 항과 없는 항이 섞여 있습니다.",
                    a,
                )
            )
        if numbered != list(range(1, len(numbered) + 1)):
            issues.append(
                _issue(
                    "warning",
                    "PARAGRAPH_NUMBER_GAP",
                    f"{a.label}의 항 번호가 순서대로가 아닙니다: {numbered}",
                    a,
                )
            )
    for p in a.paragraphs:
        where = f"{a.label}" + (f" 제{p.number}항" if p.number else "")
        issues += _check_items(p.items, where, a)
    return issues


def _item_index(it: Item) -> int | None:
    label = it.label.strip("()")
    label = label.rstrip(")")
    if it.level == "목":
        return _MOK_ORDER.find(label) + 1 or None
    return int(label) if label.isdigit() else None


def _check_items(items: list[Item], where: str, a: Article) -> list[ValidationIssue]:
    issues = []
    by_level: dict[str, list[Item]] = defaultdict(list)
    for it in items:
        by_level[it.level].append(it)
    for level, group in by_level.items():
        idx = [_item_index(it) for it in group]
        if idx != list(range(1, len(idx) + 1)):
            labels = [it.label for it in group]
            issues.append(
                _issue(
                    "warning",
                    "ITEM_NUMBER_GAP",
                    f"{where}의 {level} 번호가 순서대로가 아닙니다: {labels}",
                    a,
                )
            )
    for it in items:
        if it.children:
            issues += _check_items(
                it.children, f"{where} {it.label}{'.' if it.level != '세목' else ''}", a
            )
    return issues


def _count_items(a: Article, paragraph: int | None) -> int:
    paras = [p for p in a.paragraphs if paragraph is None or p.number == paragraph]
    return max((sum(1 for it in p.items if it.level == "호") for p in paras), default=0)


def _check_references(doc: TermsDocument) -> list[ValidationIssue]:
    issues = []
    # 약관(part)별 본문 조. 같은 약관 안에서 먼저 찾고, 없으면 다른 약관(주계약 등)에서 찾음
    # 키: (편, 조, 의N). 편-조 번호가 아니면 편은 None
    Key = tuple[int | None, int, int | None]
    body_by_part: dict[int | None, dict[Key, Article]] = defaultdict(dict)
    body_any: dict[Key, Article] = {}
    for x in doc.body_articles:
        body_by_part[x.part].setdefault((x.volume, x.number, x.sub), x)
        body_any.setdefault((x.volume, x.number, x.sub), x)
    for a in doc.articles:
        group = {
            (x.volume, x.number, x.sub): x
            for x in doc.articles
            if x.addendum == a.addendum and x.part == a.part
        }
        for ref in a.references:
            if ref.article == 0:  # 같은 조의 항
                target = a
            else:
                key = (ref.volume, ref.article, ref.sub)
                body = body_by_part[a.part].get(key) or body_any.get(key)
                # 부칙에서는 같은 부칙 안의 조를 먼저 찾고, 없으면 본문에서 찾음
                target = (group.get(key) or body) if a.addendum else body
                if target is None:
                    issues.append(
                        _issue(
                            "error",
                            "BROKEN_REFERENCE",
                            f"{a.label}에서 인용한 '{ref.text}'의 {ref.article_label}가 없습니다.",
                            a,
                        )
                    )
                    continue
                if target.deleted:
                    issues.append(
                        _issue(
                            "warning",
                            "REFERENCE_TO_DELETED",
                            f"{a.label}에서 삭제된 {target.label}를 인용합니다 ('{ref.text}').",
                            a,
                        )
                    )
                    continue
            if ref.paragraph is not None:
                numbers = {p.number for p in target.paragraphs if p.number}
                # 항 표시가 없는 조는 본문 전체가 제1항
                if ref.paragraph not in numbers and not (ref.paragraph == 1 and not numbers):
                    issues.append(
                        _issue(
                            "error",
                            "BROKEN_REFERENCE",
                            f"{a.label}에서 인용한 '{ref.text}'의 제{ref.paragraph}항이 "
                            f"{target.label}에 없습니다.",
                            a,
                        )
                    )
                    continue
            if ref.item is not None and ref.item > _count_items(target, ref.paragraph):
                issues.append(
                    _issue(
                        "error",
                        "BROKEN_REFERENCE",
                        f"{a.label}에서 인용한 '{ref.text}'의 제{ref.item}호가 {target.label}에 없습니다.",
                        a,
                    )
                )
    return issues


# ---------------------------------------------------------------- 분석 결과 검증


def _squash(s: str) -> str:
    """공백·줄바꿈·따옴표 차이를 무시하고 비교하기 위한 정규화."""
    s = re.sub(r"[\s\"'“”‘’「」『』]", "", s)
    return s


def validate_analysis(doc: TermsDocument, analysis: TermsAnalysis) -> list[ValidationIssue]:
    """AI 분석이 원문에 근거하는지 확인. 근거 없는 내용(hallucination)을 찾는 것이 목적."""
    issues: list[ValidationIssue] = []

    def add(severity, code, message, label=None, line=None):
        issues.append(
            ValidationIssue(
                severity=severity,
                code=code,
                message=message,
                article=label,
                line=line,
                source="analysis",
            )
        )

    seen: Counter[str] = Counter()
    covered: set[int] = set()
    for c in analysis.clauses:
        label = c.article.strip()
        a = doc.find(label)
        if a is None:
            add("error", "UNKNOWN_ARTICLE", f"분석 결과의 '{label}'는 원문에 없는 조입니다.", label)
            continue
        covered.add(id(a))
        seen[a.label] += 1
        if seen[a.label] == 2:
            add(
                "warning",
                "DUPLICATE_ANALYSIS",
                f"{a.label} 분석이 여러 번 나옵니다.",
                a.label,
                a.line,
            )

        if c.category not in CLAUSE_CATEGORIES:
            add(
                "info",
                "UNKNOWN_CATEGORY",
                f"{a.label}의 분류 '{c.category}'가 정해진 목록에 없습니다.",
                a.label,
                a.line,
            )
        if c.risk in ("medium", "high") and not c.issues:
            add(
                "warning",
                "RISK_WITHOUT_ISSUE",
                f"{a.label}의 위험도가 {c.risk}인데 근거(issues)가 없습니다.",
                a.label,
                a.line,
            )
        if c.risk == "none" and c.issues:
            add(
                "warning",
                "ISSUE_WITHOUT_RISK",
                f"{a.label}에 문제점이 있는데 위험도가 none 입니다.",
                a.label,
                a.line,
            )

        source = _squash(f"{a.title or ''}{a.full_text()}")
        for issue in c.issues:
            if issue.type not in UNFAIR_TYPES:
                add(
                    "info",
                    "UNKNOWN_ISSUE_TYPE",
                    f"{a.label}의 문제 유형 '{issue.type}'가 정해진 목록에 없습니다.",
                    a.label,
                    a.line,
                )
            quote = _squash(issue.quote.strip(" .…"))
            if not quote:
                add(
                    "warning",
                    "MISSING_QUOTE",
                    f"{a.label}의 지적에 원문 인용이 없습니다.",
                    a.label,
                    a.line,
                )
            elif quote not in source:
                where = next(
                    (o.label for o in doc.articles if quote in _squash(o.full_text())), None
                )
                hint = f" ({where}에 있는 문구입니다)" if where else ""
                add(
                    "error",
                    "QUOTE_NOT_FOUND",
                    f'{a.label}의 인용구가 원문에 없습니다{hint}: "{issue.quote[:60]}"',
                    a.label,
                    a.line,
                )

    for a in doc.articles:
        if not a.deleted and id(a) not in covered:
            add("info", "NOT_ANALYZED", f"{a.label}는 분석되지 않았습니다.", a.label, a.line)
    return issues
