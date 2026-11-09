"""구조화된 약관 → 사고보장 추출 묶음 (LLM 없이 규칙으로).

보장 정보를 담은 조만 골라 보장종목 단위로 묶습니다.

- 보장 약관: 보장종목 구분(《질병급여형》 등)이 있거나, '보상내용'·'보험금의 지급사유' 조가 있는 약관.
  중지·재개, 지정대리청구처럼 보장이 없는 제도성 특약은 빠집니다.
- 묶음 하나 = 약관 하나 × 보장종목 하나. 보장종목 구분이 없는 약관은 약관 전체가 묶음 하나.
- 묶음에 넣는 조: 그 보장종목의 조(제3조 보상내용, 제4조 보상하지 않는 사항 …) +
  그 조들이 인용하는 같은 약관의 조(제5조 보험가입금액 한도 등) + 보장 조와 번호가 같은 '제N조의M'
  (보장종목 공통인 제4조의2 등).
"""

import re

from pydantic import BaseModel, ConfigDict

from schema.terms import Article, TermsDocument

# 보장 내용을 담은 조의 제목
_BENEFIT_TITLE = re.compile(r"보상\s*내용|보험금의\s*지급\s*사유|보상하는\s*사항")


class Bundle(BaseModel):
    """LLM 에 한 번에 보낼 추출 단위."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    part: int | None  # TermsDocument.parts 위치
    part_title: str
    section: str | None  # 보장종목 (없으면 약관 전체)
    articles: list[Article]  # 보장종목 조 + 인용된 공통 조 (원문 순서)
    kind: str = "rider"  # main | rider

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
            chosen = {id(a) for a in own + extra}
            ordered = [a for a in live if id(a) in chosen]
            bundles.append(
                Bundle(
                    part=part,
                    part_title=_part_title(doc, part),
                    section=section,
                    articles=ordered,
                    kind=kind,
                )
            )
    return bundles
