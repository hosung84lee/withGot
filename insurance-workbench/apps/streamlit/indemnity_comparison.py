"""Extract comparable deductible rules from supported Korean policy PDF layouts."""

import re
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass, replace

import pymupdf

MAX_MB = 20
MAX_PAGES = 350
BASELINE_NAME = "삼성생명 삼성 급여 실손의료비보장보험 2601 · 4세대"


@dataclass(frozen=True)
class Deductible:
    percent: int
    minimum_manwon: tuple[int, ...] = ()
    health_rate: bool = False

    def describe(self) -> str:
        terms = [f"보장대상 의료비의 {self.percent}%"]
        if self.minimum_manwon:
            minimum = "·".join(map(str, self.minimum_manwon))
            terms.append(f"{minimum}만 원" + (" (병원급별)" if len(self.minimum_manwon) > 1 else ""))
        if self.health_rate:
            terms.append("보장대상 의료비 × 건강보험 본인부담률")
        return " / ".join(terms) + (" 중 가장 큰 금액" if len(terms) > 1 else "")


@dataclass(frozen=True)
class Evidence:
    page: int
    section: str
    excerpt: str
    rule: Deductible


@dataclass(frozen=True)
class ComparisonRow:
    label: str
    baseline: Evidence
    evidence: tuple[Evidence, ...]

    @property
    def status(self) -> str:
        rules = {item.rule for item in self.evidence}
        if not rules:
            return "근거 미확인"
        if len(rules) > 1:
            return "근거 불일치"
        return "동일" if self.baseline.rule in rules else "변경"

    @property
    def uploaded(self) -> str:
        rules = dict.fromkeys(item.rule for item in self.evidence)
        return " / ".join(rule.describe() for rule in rules) or "—"


# Verified against the supplied Samsung Life 2601 PDF (1778027111863.pdf).
# The same ordinary non-covered disease rider is the reference for both 5th-generation branches.
_BASE_INPATIENT = Evidence(
    65, "고정부가특약 질병비급여형 제3조 제1항",
    "‘비급여 의료비(비급여 병실료는 제외합니다)’(본인이 실제로 부담한 금액을 말합니다)의 "
    "70%에 해당하는 금액",
    Deductible(30),
)
_BASE_OUTPATIENT = Evidence(
    65, "고정부가특약 질병비급여형 제3조 제1항 · 표1",
    "3만원과 보장대상의료비의 30% 중 큰 금액",
    Deductible(30, (3,)),
)
BASELINE = (
    ("급여 입원", Evidence(
        31, "주계약 질병급여형 제3조 제1항",
        "전부를 본인이 부담하는 전액본인부담금을 말합니다)의 80%에 해당하는 금액",
        Deductible(20),
    )),
    ("급여 통원", Evidence(
        31, "주계약 질병급여형 제3조 제1항 · 표1",
        "1만원과 보장대상 의료비의 20% 중 큰 금액 / 2만원과 보장대상 의료비의 20% 중 큰 금액",
        Deductible(20, (1, 2)),
    )),
    ("중증 비급여 입원", _BASE_INPATIENT),
    ("중증 비급여 통원", _BASE_OUTPATIENT),
    ("비중증 비급여 입원", _BASE_INPATIENT),
    ("비중증 비급여 통원", _BASE_OUTPATIENT),
)

_RATE = r"보장대상의료비의(?P<rate>\d{1,3})%"
_LINKED = (
    r"(?:,|또는)보장대상의료비(?:×|에)건강보험본인부담률"
    r"(?:을곱한금액(?:\(주\))?)?"
)
_MAXIMUM = r"중(?:에서)?큰금액"
_SUMMARY_GROUPS = (
    r"(?<!비)-?급여\(질병\)",
    r"(?<!비)-?중증비급여\(질병\)",
    r"-?비중증비급여\(질병\)",
)
_SUMMARY_END = (
    r"-(?:(?:비?중증)?비급여(?:\(|특약)|급여\()|보장한도|\d+/\d+|$"
)


def _compact(text: str) -> str:
    # Keep the numbered paragraph boundaries used to delimit clauses.
    parts = re.split(r"([①②])", text)
    return re.sub(r"\s+", "", "".join(
        part if part in {"①", "②"} else unicodedata.normalize("NFKC", part)
        for part in parts
    ))


def _evidence(
    match: re.Match[str], page: int, section: str, rule: Deductible
) -> Evidence | None:
    if not 0 <= rule.percent <= 100:
        return None
    return Evidence(page, section, match[0], rule)


def _summary(page: int, text: str) -> Iterator[tuple[int, Evidence | None]]:
    if "자기부담금차감금액" not in text:
        return
    for group, marker in enumerate(_SUMMARY_GROUPS):
        block = re.search(marker + r"(.*?)" + r"(?=" + _SUMMARY_END + ")", text)
        if not block:
            continue
        scope = block[1]
        inpatient = re.search(r"입원치료:" + _RATE, scope)
        if inpatient:
            rule = Deductible(int(inpatient["rate"]))
            yield group * 2, _evidence(inpatient, page, "약관 요약 · 자기부담금", rule)
        outpatient = re.search(
            r"통원치료:(?:병원급별)?공제금액\((?P<low>\d+)(?:[~∼～](?P<high>\d+))?만원\)과"
            + _RATE + r"(?P<linked>" + _LINKED + r")?" + _MAXIMUM,
            scope,
        )
        if outpatient:
            minimum = (int(outpatient["low"]),)
            if outpatient["high"]:
                minimum += (int(outpatient["high"]),)
            rule = Deductible(int(outpatient["rate"]), minimum, bool(outpatient["linked"]))
            yield group * 2 + 1, _evidence(outpatient, page, "약관 요약 · 자기부담금", rule)


def _clause(page: int, text: str, group: int) -> Iterator[tuple[int, Evidence | None]]:
    heading = "질병급여형" if group == 0 else "질병비급여형"
    clause = re.search(rf"《{heading}》제3조\[보상내용\]①(.*?)(?:②|$)", text)
    if not clause:
        return
    section = f"{('주계약', '중증 비급여 특약', '비중증 비급여 특약')[group]} 제3조 제1항"
    table = clause[1]
    inpatient = re.search(
        r"입원\(입원실료,입원제비용,입원수술비\)(.{1,420}?)의(?P<paid>\d{1,3})%에해당하는금액",
        table,
    )
    if inpatient:
        rule = Deductible(100 - int(inpatient["paid"]))
        yield group * 2, _evidence(inpatient, page, section, rule)

    if "통원항목별공제금액항목공제금액" not in table:
        return
    for first in re.finditer(
        r"(?<!\d)(?P<minimum>\d+)만원(?:과|,)" + _RATE
        + r"(?P<linked>" + _LINKED + r")?" + _MAXIMUM,
        table.split("통원항목별공제금액항목공제금액", 1)[1],
    ):
        if group:
            rule = Deductible(int(first["rate"]), (int(first["minimum"]),))
            yield group * 2 + 1, _evidence(first, page, section + " · 표1", rule)
        elif first["minimum"] == "1":
            # The two hospital bands must agree on percentage and linkage.
            rate = int(first["rate"])
            second = re.search(
                r"2만원," + _RATE + r"(?P<linked>" + _LINKED + r")?" + _MAXIMUM, table
            )
            if second and rate == int(second["rate"]) and first["linked"] == second["linked"]:
                rule = Deductible(rate, (1, 2), bool(first["linked"]))
                evidence = _evidence(first, page, section + " · 표1", rule)
                if evidence:
                    yield 1, Evidence(page, evidence.section, f"{first[0]} / {second[0]}", rule)


def _readable_excerpt(source: str, excerpt: str) -> str:
    def restore(part: str) -> str:
        # Match the normalized excerpt against the source without losing its spacing.
        normalized = unicodedata.normalize("NFKC", source)
        match = re.search(r"\s*".join(re.escape(char) for char in part), normalized)
        return " ".join(match[0].split()) if match else part

    return " / ".join(restore(part) for part in excerpt.split(" / "))


def compare_pdf(data: bytes) -> list[ComparisonRow]:
    if len(data) > MAX_MB * 1024**2:
        raise ValueError(f"{MAX_MB}MB 이하의 PDF를 선택해 주세요.")
    if b"%PDF-" not in data[:1024]:
        raise ValueError("PDF 파일을 선택해 주세요.")
    evidence: list[list[Evidence]] = [[] for _ in BASELINE]
    try:
        with pymupdf.open(stream=data, filetype="pdf") as document:
            if document.needs_pass:
                raise ValueError("암호를 해제한 PDF를 선택해 주세요.")
            if not 1 <= len(document) <= MAX_PAGES:
                raise ValueError(f"1~{MAX_PAGES}쪽인 PDF를 선택해 주세요.")
            raw_pages = [page.get_text() for page in document]
    except (RuntimeError, pymupdf.FileDataError) as error:
        raise ValueError("PDF를 읽을 수 없습니다. 원본 파일을 다시 선택해 주세요.") from error

    pages = [_compact(page) for page in raw_pages]
    if not any(pages):
        raise ValueError("텍스트를 읽을 수 없습니다. 텍스트가 포함된 PDF를 선택해 주세요.")
    if not any(re.search(r"실손(?:의료비|의료)?(?:보장)?보험", page) for page in pages[:12]):
        raise ValueError("실손의료보험 약관을 확인할 수 없습니다. 표지가 포함된 PDF를 선택해 주세요.")
    has_noncritical = any("비중증비급여" in page for page in pages)
    has_critical = any(re.search(r"(?<!비)중증비급여", page) for page in pages)
    if not (has_noncritical and has_critical):
        raise ValueError("5세대의 중증·비중증 구분을 확인할 수 없습니다. 특약을 포함한 PDF를 선택해 주세요.")

    group = 0
    for number, page in enumerate(pages, 1):
        # Samsung Life places the rider title on a separate page before its article 3.
        rider = re.match(r"(비중증|중증)비급여실손의료비보장특약[^\[]+약관", page)
        if rider:
            group = 2 if rider[1] == "비중증" else 1
        for index, item in (*_summary(number, page), *_clause(number, page, group)):
            if item is not None:
                item = replace(item, excerpt=_readable_excerpt(raw_pages[number - 1], item.excerpt))
                if item not in evidence[index]:
                    evidence[index].append(item)

    return [
        ComparisonRow(label, baseline, tuple(items))
        for (label, baseline), items in zip(BASELINE, evidence, strict=True)
    ]
