"""구조화된 약관 → 사고보장 추출 묶음 (LLM 없이 규칙으로).

보장 정보를 담은 조만 골라 보장종목 단위로 묶습니다.

- 보장 약관: 보장종목 구분(《질병급여형》 등)이 있거나, '보상내용'·'보험금의 지급사유' 조가 있는 약관.
  중지·재개, 지정대리청구처럼 보장이 없는 제도성 특약은 빠집니다.
- 묶음 하나 = 약관 하나 × 보장종목 하나. 보장종목 구분이 없는 약관은 약관 전체가 묶음 하나.
- 묶음에 넣는 조: 그 보장종목의 조(제3조 보상내용, 제4조 보상하지 않는 사항 …) +
  그 조들이 인용하는 같은 약관의 조(제5조 보험가입금액 한도 등) + 보장 조와 번호가 같은 '제N조의M'
  (보장종목 공통인 제4조의2 등).
- 정액형(보장종목 구분이 없는 약관, 암보험 등)은 지급사유 조가 '별표1 참조' 뿐이라 그것만으로는
  뽑을 수 없습니다. 그래서 같은 약관의 정의 조("암"의 정의, 암보장개시일), 세부규정 조(감액·재발),
  지급하지 않는 사유 조, 그리고 별표(보험금 지급기준표, 질병 분류표)를 함께 넣습니다.
"""

import re

from pydantic import BaseModel, ConfigDict

from schema.terms import Appendix, Article, TermsDocument

# 보장 내용을 담은 조의 제목
_BENEFIT_TITLE = re.compile(r"보상\s*내용|보험금의\s*지급\s*사유|보상하는\s*사항")
# 정액형 묶음에 함께 넣는 조: 정의("암"등의 정의, 암보장개시일), 세부규정(감액·재발), 지급하지 않는 사유
_SUPPORT_TITLE = re.compile(r"정의|세부\s*규정|지급하지\s*않는\s*사유|보상하지\s*않는")
_GENERAL_DEFINITION = re.compile(r"^용어\s*의?\s*정의$")  # 계약 일반 용어 (보장과 무관, 길기만 함)
# 정액형 묶음에 넣는 별표: 지급 금액표와 대상 질병 분류표 (재해·장해 분류표, 이율 계산은 제외)
_APPENDIX_WANTED = re.compile(r"지급\s*기준표|신생물|종양|분류표")
_APPENDIX_SKIP = re.compile(r"재\s*해|장\s*해|이율|신체부위")
APPENDIX_MAX_CHARS = 3500  # 지급기준표에서 넣는 분량 (금액표 + 주석)
TABLE_MAX_CHARS = 1300  # 분류표에서 넣는 분량 (앞쪽에 질병 코드, 뒤는 KCD 개정 설명 반복)


class Bundle(BaseModel):
    """LLM 에 한 번에 보낼 추출 단위."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    part: int | None  # TermsDocument.parts 위치
    part_title: str
    section: str | None  # 보장종목 (없으면 약관 전체)
    articles: list[Article]  # 보장종목 조 + 인용된 공통 조 (원문 순서)
    kind: str = "rider"  # main | rider
    appendices: list[Appendix] = []  # 정액형: 보험금 지급기준표·분류표

    @property
    def key(self) -> str:
        return f"{self.part_title} · {self.section}" if self.section else self.part_title

    def article_block(self, a: Article) -> str:
        head = f"### {a.label}" + (f" ({a.title})" if a.title else "")
        if a.section:
            head += f" 《{a.section}》"
        return f"{head}\n{a.full_text()}"

    def render(self) -> str:
        """프롬프트에 넣을 본문. 조마다 '### 제3조 (보상내용) 《질병급여형》' 머리를 붙임."""
        lines = [f"약관: {self.part_title}"]
        if self.section:
            lines.append(f"보장종목: {self.section}")
        lines.append("")
        lines += [self.article_block(a) for a in self.articles]
        for x in self.appendices:
            limit = APPENDIX_MAX_CHARS if "지급기준표" in x.label else TABLE_MAX_CHARS
            text = x.text
            if len(text) > limit:
                text = text[:limit] + "\n… (이하 생략)"
            lines.append(f"### {x.label}\n{text}")
        return "\n\n".join(lines)


def _part_title(doc: TermsDocument, part: int | None) -> str:
    if part is None:
        return doc.title or "약관"
    return doc.parts[part].title


def _is_benefit_part(arts: list[Article]) -> bool:
    return any(a.section for a in arts) or any(_BENEFIT_TITLE.search(a.title or "") for a in arts)


def _referenced(arts: list[Article], pool: list[Article]) -> list[Article]:
    """arts 의 본문이 인용하는 pool 의 조 (보장종목 없는 공통 조만)."""
    wanted = {
        (r.volume, r.article, r.sub)
        for a in arts
        for r in a.references
        if r.article and not r.section
    }
    return [x for x in pool if x.section is None and (x.volume, x.number, x.sub) in wanted]


def _part_appendices(doc: TermsDocument, part: int | None) -> list[Appendix]:
    """약관(part) 범위 안의 지급기준표·분류표 별표. 별표 번호는 약관마다 1부터라 줄 번호로 범위를 잡음."""
    if part is None or not doc.parts:
        pool = doc.appendices
    else:
        lo = doc.parts[part].line
        hi = doc.parts[part + 1].line if part + 1 < len(doc.parts) else float("inf")
        pool = [x for x in doc.appendices if lo <= x.line < hi]
    return [
        x
        for x in pool
        if x.label.startswith("별표")
        and _APPENDIX_WANTED.search(x.label)
        and not _APPENDIX_SKIP.search(x.label)
    ]


def build_bundles(doc: TermsDocument) -> list[Bundle]:
    parts: dict[int | None, list[Article]] = {}
    for a in doc.body_articles:
        parts.setdefault(a.part, []).append(a)

    bundles: list[Bundle] = []
    first_benefit_part = True
    for part, arts in parts.items():
        live = [a for a in arts if not a.deleted]
        if not _is_benefit_part(live):
            continue
        kind = "main" if first_benefit_part else "rider"
        first_benefit_part = False
        sections = list(dict.fromkeys(a.section for a in live if a.section))
        groups = (
            [(s, [a for a in live if a.section == s]) for s in sections]
            if sections
            else [(None, [a for a in live if _BENEFIT_TITLE.search(a.title or "")])]
        )
        for section, own in groups:
            numbers = {(a.volume, a.number) for a in own}
            extra = _referenced(own, live) + [
                a
                for a in live
                if a.section is None and a.sub is not None and (a.volume, a.number) in numbers
            ]
            appendices: list[Appendix] = []
            if section is None:  # 정액형: 정의·세부규정·부지급 조와 지급기준표·분류표 별표
                extra += [
                    a
                    for a in live
                    if _SUPPORT_TITLE.search(a.title or "")
                    and not _GENERAL_DEFINITION.match((a.title or "").strip())
                ]
                appendices = _part_appendices(doc, part)
            chosen = {id(a) for a in own + extra}
            ordered = [a for a in live if id(a) in chosen]
            bundles.append(
                Bundle(
                    part=part,
                    part_title=_part_title(doc, part),
                    section=section,
                    articles=ordered,
                    kind=kind,
                    appendices=appendices,
                )
            )
    return bundles
