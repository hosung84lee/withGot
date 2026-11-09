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

보험사 약관 PDF 는 본문 앞에 목차·안내 페이지가 붙어 있어서 다음을 따로 처리합니다.
- 목차 줄: 제목 뒤에 쪽 번호만 있는 줄 ('제 1 조 [보장종목] 5', '[별표 1] 용어의 정의 35')은 건너뜀
- 두 줄로 끊긴 괄호 제목 ('제4조의2 [‘기본형 …에서' + '보상하지 않는 사항]')은 이어 붙여 읽음
- 별표 뒤에 다시 관 제목이나 괄호 제목 조가 나오면 별표를 닫고 본문으로 돌아감
  (주계약 별표 뒤에 특약 약관이 이어지는 PDF)
- 목차·안내 페이지에서 잡힌 본문 없는 조와 빈 관 제목은, 뒤에 같은 조·관의 실제 본문이
  있으면 지움
- 주계약 약관 뒤에 특약 약관이 이어지는 PDF 는 '○○특약(무배당) 약관' 같은 제목 줄에서
  약관(part)을 나눔. 조 번호는 약관마다 1부터 다시 시작
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
    TermsPart,
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
# 괄호 제목 뒤에 오면 인용 ('제2조의6(…의 정의)에 따라', '제3조(보험금의 지급사유) 제1항 제2호의')
# '이' 는 본문 첫 글자일 수 있어 뺌 ('제1조(목적) 이 약관은')
_INLINE_AFTER_TITLE = re.compile(
    r"^(에|의|및|와|과|를|을|로|으로|부터|까지|에서|[,、]|제\s*\d+\s*(항|호))"
)

# 조 번호 뒤의 조 제목 괄호 ('제8조(보험금의 지급절차) 제4항'). 괄호 한 겹까지 중첩 허용
_REF_TITLE = r"[(（](?:[^()（）]|[(（][^()（）]*[)）]){1,60}[)）]"
_REF = re.compile(
    r"제\s*(\d+)\s*조(?:\s*의\s*(\d+))?"
    rf"(?:\s*{_REF_TITLE})?"
    r"(?:\s*제\s*(\d+)\s*항)?(?:\s*제\s*(\d+)\s*호)?"
)
_PARA_REF = re.compile(r"제\s*(\d+)\s*항")
# 인용 바로 앞이 법령 이름이면 다른 법의 조문 ('상법 제638조', '「약관법」 제6조', '｢전자서명법｣')
# '방법' 은 법령 이름이 아님 ('보험금을 받는 방법 제9조')
_EXTERNAL_BEFORE = re.compile(r"(」|』|｣|(?<!방)법|법률|령|규칙|규정|조례|협약|고시)\s*$")
# 앞 인용과 이어지는 범위·나열 ('제1항부터 제7항', '제15항 및 제19항', '제4조부터 제5조의3까지')
_REF_CONNECT = re.compile(r"^(?:\s|[,·ㆍ~～\-]|및|또는|부터|에서|내지|와|과)*$")
# 법령 이름을 찾을 때 볼 앞 문맥 길이
_REF_LOOKBACK = 40
# 목차 줄 끝의 쪽 번호
_TOC_PAGE = re.compile(r"^\d{1,3}$")
_TOC_TITLE_PAGE = re.compile(r"^\S.*\s\d{1,3}$")
# 괄호 제목이 다음 줄에서 닫히는 경우, 닫는 괄호 뒤
_CLOSE_TAIL = re.compile(r"^[^\[\]【】〔〕［］]*[\]】〕］)]\s*(.*)$")
# 목차 제목과 본문 제목을 비교할 때 공백·문장부호 무시
_TITLE_NOISE = re.compile(r"[\s\W_]+")
# 본문 없는 조로 보는 길이 (목차·안내 페이지의 조 제목 줄)
_STUB_MAX = 200
# 약관 제목 줄: '지정대리청구서비스특약 약관', '삼성 인터넷암보험(2404)(갱신형,무배당) 약관'
_PART_TITLE = re.compile(r"^\S.{1,80}\s?약관$")
_PARENS = re.compile(r"\([^()]*\)")
_PART_NOISE = re.compile(r"[,“”\"'‘’]|에서|할 때")
_PART_NEXT = re.compile(r"^(※|제\s*1\s*(관|장|편|조))")
# 표지·목차의 분류 이름. 약관 제목으로 보지 않음
_PART_GENERIC = {"약관", "보험약관", "주계약약관", "특약약관", "제도성특약약관"}
# 부록 (약관에서 인용된 법령 등): 법령 조문이 이어지므로 구조화하지 않고 원문 보관
_ANNEX = re.compile(r"^[\[【]?\s*부\s*록\s*[\]】]?\s*(\S.*)$")


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
    if title is not None and _INLINE_AFTER_TITLE.match(body):
        return None  # 줄 맨 앞에 온 '제N조(제목)에 따라' 같은 인용
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
        self.part: int | None = None  # 현재 약관 (doc.parts 위치)
        self.annex = False  # 부록 안: 새 약관이나 제1관이 나올 때까지 원문 그대로 보관

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
        h = Heading(kind=kind, number=number, title=title, line=line, part=self.part)  # type: ignore[arg-type]
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
            part=self.part,
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

    def start_part(self, title: str, line: int) -> None:
        """새 약관 시작: 제목 경로·부칙·별표를 모두 닫음."""
        self._close_addendum_text()
        self.part = len(self.doc.parts)
        self.doc.parts.append(TermsPart(title=title, line=line))
        self.stack = []
        self.article = self.paragraph = None
        self.appendix = None
        self.annex = False
        self.addendum = 0
        self.last = None
        self._reset_items()

    def start_appendix(self, label: str, line: int, annex: bool = False) -> None:
        self._close_addendum_text()
        self.appendix = Appendix(label=label, text="", line=line)
        self.doc.appendices.append(self.appendix)
        self.annex = annex

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
        _drop_toc_stubs(doc)
        _drop_empty_parts(doc)
        for a in doc.articles:
            a.references = extract_references(a.full_text())
        return doc


def _norm_title(title: str | None) -> str:
    return _TITLE_NOISE.sub("", title or "")


def _same_title(a: str | None, b: str | None) -> bool:
    na, nb = _norm_title(a), _norm_title(b)
    if not na or not nb:
        return True  # 제목 한쪽이 없으면 번호만으로 판단
    return na == nb or na.startswith(nb) or nb.startswith(na)


def _drop_toc_stubs(doc: TermsDocument) -> None:
    """목차·안내 페이지에서 잡힌 조와 관 제목을 지움.

    본문이 거의 없는 조 뒤에 같은 번호·같은 제목의 조가 더 긴 본문으로 다시 나오면
    앞의 것은 목차 항목으로 봅니다. 아래에 조가 하나도 남지 않은 관 제목도
    뒤에 같은 관 제목이 다시 나오면 지웁니다.
    """
    arts = doc.articles
    lengths = [len(a.full_text()) for a in arts]
    has_parts = any(a.part is not None for a in arts)
    keep: list[Article] = []
    for i, a in enumerate(arts):
        n = lengths[i]
        later = arts[i + 1 :]
        # 다른 특약의 같은 번호 조는 지우지 않음 (목차는 약관 제목 줄 앞이라 part 가 None)
        stub = n < _STUB_MAX and any(
            b.label == a.label
            and (a.part is None or a.part == b.part)
            and _same_title(a.title, b.title)
            and lengths[j] >= max(2 * n, n + 40)
            for j, b in enumerate(later, start=i + 1)
        )
        # 첫 약관 제목 줄 앞(표지·안내)의 조가 뒤 약관에 같은 번호·같은 제목으로 다시 나오면
        # 안내 페이지 항목. 뒤따르는 안내문까지 본문으로 붙어 길어졌을 수 있어 길이는 보지 않음
        if not stub and has_parts and a.part is None and a.title:
            stub = any(
                b.part is not None
                and b.label == a.label
                and _norm_title(b.title) == _norm_title(a.title)
                for b in later
            )
        if not stub:
            keep.append(a)
    doc.articles = keep

    heads = doc.headings
    art_lines = sorted(a.line for a in keep)
    kept_heads: list[Heading] = []
    for i, h in enumerate(heads):
        end = heads[i + 1].line if i + 1 < len(heads) else float("inf")
        has_article = any(h.line < ln < end for ln in art_lines)
        repeated = any(
            g.kind == h.kind
            and g.number == h.number
            and (h.part is None or h.part == g.part)
            and _same_title(g.title, h.title)
            for g in heads[i + 1 :]
        )
        if has_article or not repeated:
            kept_heads.append(h)
    doc.headings = kept_heads

    # 목차에서 잡힌 별표·부록 (내용이 거의 없고 뒤에 같은 제목이 다시 나옴)
    apps = doc.appendices
    doc.appendices = [
        x
        for i, x in enumerate(apps)
        if len(x.text) >= _STUB_MAX
        or not any(
            _same_title(x.label, y.label) and len(y.text) > len(x.text) for y in apps[i + 1 :]
        )
    ]


def _drop_empty_parts(doc: TermsDocument) -> None:
    """조도 관 제목도 없는 약관 제목(목차 페이지의 '주계약 약관' 등)을 지우고 번호를 다시 매김.

    관 제목은 있는데 조가 없는 약관(지원하지 않는 '제1-1조' 번호 등)은 남겨서 검증에서 알립니다.
    """
    used = sorted({x.part for x in [*doc.articles, *doc.headings] if x.part is not None})
    remap = {old: new for new, old in enumerate(used)}
    doc.parts = [doc.parts[i] for i in used]
    for x in [*doc.articles, *doc.headings]:
        x.part = remap.get(x.part) if x.part is not None else None


def _part_title(lines: list[str], i: int) -> str | None:
    """약관 제목 줄이면 제목. 앞 줄이 쪽 번호(새 페이지)이거나 다음 줄이 ※ 안내·제1관·제1조여야 함."""
    line = lines[i]
    if not _PART_TITLE.match(line) or len(line) > 90:
        return None
    if _TITLE_NOISE.sub("", line) in _PART_GENERIC:
        return None
    if line[0].isdigit() or circled_value(line[0]) or line[0] in "ㆍ∙·-":
        return None
    if _PART_NOISE.search(_PARENS.sub("", line)):
        return None
    if _ARTICLE.match(line) or _HEADING.match(line) or _APPENDIX.match(line):
        return None
    prev = next((ln for ln in reversed(lines[max(0, i - 4) : i]) if ln), "")
    nxt = next((ln for ln in lines[i + 1 : i + 5] if ln), "")
    if (prev and _PAGE_NO.match(prev)) or _PART_NEXT.match(nxt):
        return line
    return None


def normalize(text: str) -> list[str]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("　", " ").replace("\xa0", " ").replace("﻿", "")
    return [ln.strip() for ln in text.split("\n")]


def _join_split_title(lines: list[str], i: int) -> tuple[str, int]:
    """'제N조 [제목 앞부분' 처럼 괄호가 안 닫힌 조 시작 줄이면 다음 줄과 이어 붙임.

    (이어 붙인 줄, 함께 읽은 줄 수) 를 돌려줍니다. 해당 없으면 (원래 줄, 0).
    """
    line = lines[i]
    m = _ARTICLE.match(line)
    if not m:
        return line, 0
    rest = m.group(3).strip()
    if not rest or rest[0] not in _OPEN or _OPEN[rest[0]] in rest:
        return line, 0
    for k in (1, 2):
        if i + k >= len(lines):
            break
        nxt = lines[i + k]
        if not nxt:
            continue
        if _CLOSE_TAIL.match(nxt):
            return f"{line} {nxt}", k
        break
    return line, 0


def _is_toc_entry(line: str) -> bool:
    """제목 뒤에 쪽 번호만 붙은 목차 줄인지."""
    if (h := _parse_article_header(line)) is not None:
        _, _, title, body, _ = h
        return title is not None and bool(_TOC_PAGE.match(body))
    m = _APPENDIX.match(line)
    if m and m.group(1) and m.group(4) and _parse_appendix_header(line) is not None:
        return bool(_TOC_TITLE_PAGE.match(m.group(5).strip()))
    if m := _HEADING.match(line):
        return bool(_TOC_TITLE_PAGE.match((m.group(3) or "").strip()))
    if m := _ANNEX.match(line):
        return bool(_TOC_TITLE_PAGE.match(m.group(1)) or re.search(r"\D\s?\d{1,3}$", m.group(1)))
    return False


def _heading_match(line: str) -> tuple[str, int, str] | None:
    if m := _HEADING.match(line):
        title = (m.group(3) or "").strip()
        if len(title) <= 40 and not title.endswith("."):
            return m.group(2), int(m.group(1)), title
    return None


def _resumes_body(line: str) -> bool:
    """별표 안에서 본문이 다시 시작되는 줄인지 (관 제목, 또는 괄호 제목이 붙은 조)."""
    if (h := _heading_match(line)) is not None and h[0] in ("편", "장", "관"):
        return True
    m = _ARTICLE.match(line)
    rest = m.group(3).strip() if m else ""
    return bool(rest) and rest[0] in _OPEN and _parse_article_header(line) is not None


def parse_terms(text: str) -> TermsDocument:
    b = _Builder()
    lines = normalize(text)
    i = 0
    while i < len(lines):
        lineno = i + 1
        line, used = _join_split_title(lines, i)
        i += 1 + used
        if not line or _PAGE_NO.match(line):
            continue
        if _is_toc_entry(line):
            continue
        if not used and (title := _part_title(lines, lineno - 1)) is not None:
            b.start_part(title, lineno)
            continue

        if b.annex:
            hm = _heading_match(line)
            if hm and hm[0] in ("편", "장", "관") and hm[1] == 1:
                b.appendix, b.annex = None, False  # 부록 뒤에 새 약관 본문 시작
            else:
                b.appendix.text = f"{b.appendix.text}\n{line}".strip()
                continue
        if m := _ANNEX.match(line):
            b.start_appendix(f"부록 {m.group(1)}", lineno, annex=True)
            continue

        if _ADDENDUM.match(line):
            b.start_addendum(line)
            continue
        if (label := _parse_appendix_header(line)) is not None:
            b.start_appendix(label, lineno)
            continue
        if b.appendix:
            if _resumes_body(line):
                b.appendix = None
            else:  # 별표 안의 내용은 구조화하지 않고 그대로 보관
                b.appendix.text = f"{b.appendix.text}\n{line}".strip()
                continue
        if (hm := _heading_match(line)) and not b.addendum:
            b.heading(hm[0], hm[1], hm[2], lineno)
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
    단, 앞 인용에 범위·나열로 이어지면 ('제3조(보상내용) 제1항부터 제7항') 앞 인용의 조를 따릅니다.
    법령 이름은 PDF 줄바꿈으로 앞 줄에 있을 수 있어 줄을 넘어 앞 문맥을 봅니다.
    """
    events: list[tuple[int, re.Match[str], bool]] = []  # (시작 위치, 매치, 조 인용인지)
    taken: list[tuple[int, int]] = []
    for m in _REF.finditer(text):
        taken.append(m.span())
        events.append((m.start(), m, True))
    for m in _PARA_REF.finditer(text):
        if not any(s <= m.start() < e for s, e in taken):
            events.append((m.start(), m, False))
    events.sort(key=lambda e: e[0])

    refs: list[ArticleRef] = []
    # 직전 인용: (끝 위치, 다른 법령인지, 조 번호, 의N). 조 번호 0 은 '같은 조'
    last: tuple[int, bool, int, int | None] | None = None
    for start, m, is_article in events:
        chained = last is not None and bool(_REF_CONNECT.match(text[last[0] : start]))
        if is_article:
            art, sub, para, item = m.groups()
            before = text[max(0, start - _REF_LOOKBACK) : start].replace("\n", " ")
            external = bool(_EXTERNAL_BEFORE.search(before)) or (chained and last[1])
            last = (m.end(), external, int(art), int(sub) if sub else None)
            if external:
                continue
            refs.append(
                ArticleRef(
                    text=m.group(0),
                    article=int(art),
                    sub=int(sub) if sub else None,
                    paragraph=int(para) if para else None,
                    item=int(item) if item else None,
                )
            )
            continue
        # 조 없이 항만 쓴 인용
        if chained:
            _, external, art, sub = last
        else:
            external, art, sub = False, 0, None
        last = (m.end(), external, art, sub)
        if not external:
            refs.append(
                ArticleRef(text=m.group(0), article=art, sub=sub, paragraph=int(m.group(1)))
            )
    return refs
