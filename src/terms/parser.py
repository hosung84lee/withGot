"""약관 원문(텍스트) → TermsDocument 구조화.

LLM 없이 규칙(정규식)으로 나눕니다. 결과가 매번 같고, 줄 번호로 원문 위치를 되짚을 수 있습니다.

인식하는 표기
- 상위 제목: 제1편 / 제1장 / 제1절 / 제1관 + 제목
- 조:      제1조(목적), 제1조 [목적], 제3조의2(…), 제5조 삭제, 제1조 목적
- 항:      ① ② … ㊿
- 호:      1.  2.
- 목:      가.  나.
- 세목:    1)  (1)
- 부칙:    부칙, 부 칙, 부칙 <2024.1.1.>
- 별표:    [별표 1] …, 별표 2 …, 【별지 1】 …

한 줄에 하나의 표기만 시작한다고 가정합니다 (PDF 에서 뽑은 텍스트의 일반적인 모양).
표기가 없는 줄은 바로 앞 요소의 본문이 이어지는 것으로 봅니다.
"""

import re

from schema.terms import (
    HEADING_LEVEL,
    Appendix,
    Article,
    ArticleRef,
    Heading,
    Item,
    Paragraph,
    TermsDocument,
)

# ---------------------------------------------------------------- 표기 패턴


def circled_value(ch: str) -> int | None:
    """①~⑳, ㉑~㉟, ㊱~㊿ → 숫자."""
    o = ord(ch)
    if 0x2460 <= o <= 0x2473:
        return o - 0x2460 + 1
    if 0x3251 <= o <= 0x325F:
        return o - 0x3251 + 21
    if 0x32B1 <= o <= 0x32BF:
        return o - 0x32B1 + 36
    return None


_ARTICLE = re.compile(r"^제\s*(\d+)\s*조(?:\s*의\s*(\d+))?\s*(.*)$")
_HEADING = re.compile(r"^제\s*(\d+)\s*(편|장|절|관)(?:\s+(.*))?$")
_ADDENDUM = re.compile(r"^부\s*칙\s*(?:[<〈(\[［【].*)?$")
_APPENDIX = re.compile(r"^([\[【〔<［(])?\s*(별\s*표|별\s*지)\s*(\d*)\s*([\]】〕>］)])?(.*)$")
_HO = re.compile(r"^(\d{1,2})\.(?!\d)\s*(.*)$")
_MOK = re.compile(r"^([가나다라마바사아자차카타파하])\.\s*(.*)$")
_SEMOK = re.compile(r"^(\(\d{1,2}\)|\d{1,2}\))\s*(.*)$")
_PAGE_NO = re.compile(r"^[-–—\s]*\d+\s*(/\s*\d+)?[-–—\s]*$|^-\s*\d+\s*-$")
_OPEN = {"(": ")", "[": "]", "【": "】", "〔": "〕", "［": "］", "<": ">"}
# 조 번호 바로 뒤에 오면 조 제목이 아니라 문장 속 인용 ('제3조에 따라')
_PARTICLE_START = tuple("에의및와과를을는은이가로으부까도만")

_REF = re.compile(
    r"제\s*(\d+)\s*조(?:\s*의\s*(\d+))?(?:\s*제\s*(\d+)\s*항)?(?:\s*제\s*(\d+)\s*호)?"
)
_PARA_REF = re.compile(r"제\s*(\d+)\s*항")
# 인용 바로 앞이 법령 이름이면 다른 법의 조문 ('상법 제638조', '「약관법」 제6조')
_EXTERNAL_BEFORE = re.compile(r"(」|』|법|법률|령|규칙|규정|조례|협약|고시)\s*$")


def _split_title(rest: str) -> tuple[str | None, str]:
    """조 번호 뒤 문자열 → (제목, 나머지 본문)."""
    if rest and rest[0] in _OPEN:
        close = rest.find(_OPEN[rest[0]])
        if close > 0:
            return rest[1:close].strip(), rest[close + 1 :].strip()
    return None, rest


def _parse_article_header(line: str) -> tuple[int, int | None, str | None, str, bool] | None:
    """조 시작 줄이면 (번호, 의N, 제목, 나머지 본문, 삭제여부). 본문 속 인용이면 None."""
    m = _ARTICLE.match(line)
    if not m:
        return None
    number, sub, rest = int(m.group(1)), m.group(2), m.group(3).strip()
    title, body = _split_title(rest)
    if title is None:
        if not rest or circled_value(rest[0]) or rest.startswith("삭제"):
            pass
        elif (
            len(rest) <= 25
            and not rest.startswith(_PARTICLE_START)
            and not rest.endswith(".")
            and not rest.startswith("제")
            and not re.match(r"^\s*\d", rest)
        ):
            title, body = rest, ""  # '제1조 목적' 처럼 괄호 없는 제목
        else:
            return None
    deleted = title == "삭제" or body.startswith("삭제")
    if title == "삭제":
        title = None
    return number, int(sub) if sub else None, title, body, deleted


def _parse_appendix_header(line: str) -> str | None:
    m = _APPENDIX.match(line)
    if not m:
        return None
    opened, kind, num, closed, rest = m.groups()
    if not opened and rest and not rest[0].isspace():
        return None  # '별표1에 따른' 같은 본문 속 인용
    if opened and not closed and not num and rest and not rest[0].isspace():
        return None
    label = f"{kind.replace(' ', '')} {num}".strip()
    rest = rest.strip()
    return f"{label} {rest}".strip() if rest else label


# ---------------------------------------------------------------- 파서


class _Builder:
    def __init__(self) -> None:
        self.doc = TermsDocument()
        self.stack: list[Heading] = []  # 현재 열린 상위 제목
        self.article: Article | None = None
        self.paragraph: Paragraph | None = None
        self.items: dict[str, Item | None] = {"호": None, "목": None, "세목": None}
        self.addendum = 0  # 0: 본문, n: n번째 부칙
        self.addendum_lines: list[str] = []
        self.appendix: Appendix | None = None
        self.preamble: list[str] = []
        self.last: Item | Paragraph | None = None  # 이어지는 줄을 붙일 대상

    # --- 이어 쓰기
    def _append(self, text: str) -> None:
        if self.appendix:
            self.appendix.text = f"{self.appendix.text}\n{text}".strip()
        elif self.last is not None:
            self.last.text = f"{self.last.text}\n{text}" if self.last.text else text
        elif self.addendum:
            self.addendum_lines.append(text)
        else:
            self.preamble.append(text)

    def _reset_items(self) -> None:
        self.items = {"호": None, "목": None, "세목": None}

    def _close_addendum_text(self) -> None:
        if self.addendum_lines:
            self.doc.addendum_text.append("\n".join(self.addendum_lines))
            self.addendum_lines = []

    def _ensure_paragraph(self) -> Paragraph:
        assert self.article is not None
        if self.paragraph is None:
            self.paragraph = Paragraph()
            self.article.paragraphs.append(self.paragraph)
        return self.paragraph

    # --- 각 표기
    def heading(self, kind: str, number: int, title: str, line: int) -> None:
        h = Heading(kind=kind, number=number, title=title, line=line)  # type: ignore[arg-type]
        level = HEADING_LEVEL[kind]
        self.stack = [s for s in self.stack if HEADING_LEVEL[s.kind] < level] + [h]
        self.doc.headings.append(h)
        self.article = self.paragraph = None
        self.last = None
        self._reset_items()

    def start_article(
        self, number: int, sub: int | None, title: str | None, body: str, deleted: bool, line: int
    ) -> None:
        self._close_addendum_text()
        self.article = Article(
            number=number,
            sub=sub,
            title=title,
            deleted=deleted,
            path=[] if self.addendum else [h.label for h in self.stack],
            addendum=self.addendum or None,
            line=line,
        )
        self.doc.articles.append(self.article)
        self.paragraph = None
        self._reset_items()
        self.last = None
        if body and not (deleted and body.startswith("삭제")):
            self.line(body, line)

    def start_addendum(self, text: str) -> None:
        self._close_addendum_text()
        self.addendum += 1
        self.doc.addenda.append(text)
        self.article = self.paragraph = None
        self.appendix = None
        self.last = None
        self._reset_items()

    def start_appendix(self, label: str, line: int) -> None:
        self._close_addendum_text()
        self.appendix = Appendix(label=label, text="", line=line)
        self.doc.appendices.append(self.appendix)

    def line(self, text: str, lineno: int) -> None:
        """조 본문 안의 한 줄: 항 / 호 / 목 / 세목 / 이어지는 줄."""
        if self.article is None:
            self._append(text)
            return

        n = circled_value(text[0])
        if n:
            self.paragraph = Paragraph(number=n, text=text[1:].strip())
            self.article.paragraphs.append(self.paragraph)
            self._reset_items()
            self.last = self.paragraph
            return

        for level, pattern in (("호", _HO), ("목", _MOK), ("세목", _SEMOK)):
            m = pattern.match(text)
            if not m:
                continue
            label = m.group(1)
            item = Item(level=level, label=label, text=m.group(2).strip())  # type: ignore[arg-type]
            parent = {
                "호": None,
                "목": self.items["호"],
                "세목": self.items["목"] or self.items["호"],
            }[level]
            if parent is not None:
                parent.children.append(item)
            else:
                self._ensure_paragraph().items.append(item)
            self.items[level] = item
            if level == "호":
                self.items["목"] = self.items["세목"] = None
            elif level == "목":
                self.items["세목"] = None
            self.last = item
            return

        if self.last is None:
            self.last = self._ensure_paragraph()
        self._append(text)

    def finish(self) -> TermsDocument:
        self._close_addendum_text()
        doc = self.doc
        lines = [p for p in self.preamble if p]
        if lines and not doc.title and len(lines[0]) <= 60:
            doc.title = lines.pop(0)
        doc.preamble = "\n".join(lines)
        for a in doc.articles:
            a.references = extract_references(a.full_text())
        return doc


def normalize(text: str) -> list[str]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("　", " ").replace("\xa0", " ").replace("﻿", "")
    return [ln.strip() for ln in text.split("\n")]


def parse_terms(text: str) -> TermsDocument:
    b = _Builder()
    for lineno, line in enumerate(normalize(text), start=1):
        if not line or _PAGE_NO.match(line):
            continue

        if _ADDENDUM.match(line):
            b.start_addendum(line)
            continue
        if (label := _parse_appendix_header(line)) is not None:
            b.start_appendix(label, lineno)
            continue
        if b.appendix:  # 별표 안의 내용은 구조화하지 않고 그대로 보관
            b.appendix.text = f"{b.appendix.text}\n{line}".strip()
            continue
        if (m := _HEADING.match(line)) and not b.addendum:
            title = (m.group(3) or "").strip()
            if len(title) <= 40 and not title.endswith("."):
                b.heading(m.group(2), int(m.group(1)), title, lineno)
                continue
        if (h := _parse_article_header(line)) is not None:
            b.start_article(*h, line=lineno)
            continue
        b.line(line, lineno)
    return b.finish()


# ---------------------------------------------------------------- 조항 인용


def extract_references(text: str) -> list[ArticleRef]:
    """본문 속 '제N조(의M)(제K항)(제L호)' 인용. 다른 법령 조문은 제외합니다.

    '제2항' 처럼 조 없이 항만 쓴 인용은 article=0 (같은 조) 으로 둡니다.
    """
    refs: list[ArticleRef] = []
    taken: list[tuple[int, int]] = []
    for m in _REF.finditer(text):
        taken.append(m.span())
        before = text[max(0, m.start() - 30) : m.start()].split("\n")[-1]
        if _EXTERNAL_BEFORE.search(before):
            continue
        art, sub, para, item = m.groups()
        refs.append(
            ArticleRef(
                text=m.group(0),
                article=int(art),
                sub=int(sub) if sub else None,
                paragraph=int(para) if para else None,
                item=int(item) if item else None,
            )
        )
    for m in _PARA_REF.finditer(text):
        if any(s <= m.start() < e for s, e in taken):
            continue
        refs.append(ArticleRef(text=m.group(0), article=0, paragraph=int(m.group(1))))
    return refs
