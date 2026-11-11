"""실제 병원 서식 읽기 (규칙 기반, LLM 없음).

PDF 한 개에 여러 서류가 묶여 있어도(영수증 + 세부산정내역 + 진단서 + …) 제목 줄로 나눠 각각 읽습니다.

지원 서식
- 진료비 계산서·영수증 (국민건강보험 요양급여의 기준에 관한 규칙 별지 서식 모양)
- 진료비 세부산정내역
- 진단서 (의료법 시행규칙 별지 제5호의2 서식 모양)
- 입·퇴원 확인서, 병리검사 결과지, 방사선치료 확인서 → 종류만 구분 (내용은 2단계: AI 판단 입력)

텍스트 PDF 만 됩니다 (스캔본·사진은 글자가 없어 읽지 못함).
"""

import re

from .documents import Item, MedicalDoc

_CHECK = r"\[\s*[√✓VvOo■]\s*\]"
_KCD_TOKEN = r"[A-Z]\d{2}(?:\.\d{1,2})?"
_DATE = r"\d{4}\.\d{2}\.\d{2}"

# 제목 줄(공백 제거 후) → 서류 종류. 줄 전체가 제목이어야 하는 것은 fullmatch
_HEADERS: list[tuple[re.Pattern, str]] = [
    (re.compile(r".*(외래|입원).*진료비계산서.?영수증$"), "RECEIPT"),
    (re.compile(r"^진료비세부산정내역(서)?$"), "DETAIL"),
    (re.compile(r"^진단서$"), "DIAGNOSIS"),
    (re.compile(r"^입.?퇴원확인서$"), "ADMISSION"),
    (re.compile(r"^병리검사결과지$"), "PATHOLOGY"),
    (re.compile(r"^방사선치료확인서.*"), "RADIATION"),
]
_FACILITY_KIND = [
    ("상급종합병원", "상급종합병원"),
    ("종합병원", "종합병원"),
    ("병원급", "병원"),
    ("의원급", "의원"),
]
# 세부산정내역 한 줄: [분류] 일자 코드 명칭 금액 횟수 일수 총액 본인부담금 공단부담금 전액본인부담 비급여
_DETAIL_ROW = re.compile(
    r"^(?:(?P<cat>\S+)\s+)?(?P<date>\d{2}\.\d{2}(?:~(?:\d{2}\.\d{2})?)?)\s+(?P<code>\S+)\s+"
    r"(?P<name>.+?)\s+(?P<nums>(?:[\d,]+\s+){7}[\d,]+)$"
)
_TOTAL_ROW = re.compile(r"^합\s*계\s+((?:[\d,]+\s+){3,4}[\d,]+)$")


def _n(s: str) -> int:
    return int(s.replace(",", ""))


def is_hospital_form(text: str) -> bool:
    return any(_kind_of_line(line) for line in text.splitlines())


def _kind_of_line(line: str) -> str | None:
    sq = re.sub(r"\s+", "", line)
    if not sq or len(sq) > 60:
        return None
    for pattern, kind in _HEADERS:
        if pattern.match(sq):
            return kind
    return None


def split_documents(text: str) -> list[tuple[str, str]]:
    """묶음 텍스트 → [(종류, 그 서류 텍스트)]. 제목 줄에서 새 서류가 시작."""
    out: list[tuple[str, list[str]]] = []
    for line in text.splitlines():
        kind = _kind_of_line(line)
        if kind:
            out.append((kind, [line]))
        elif out:
            out[-1][1].append(line)
    return [(k, "\n".join(lines)) for k, lines in out]


def _period(text: str, doc: MedicalDoc) -> None:
    m = re.search(rf"({_DATE})\s*~\s*({_DATE})", text)
    if m:
        doc.fields["진료기간"] = f"{m.group(1)} ~ {m.group(2)}"
        doc.fields["진료일"] = m.group(1).replace(".", "-")
    if "산정특례" in text:
        doc.fields["환자구분"] = "건강보험(산정특례)"


def _receipt(filename: str, text: str) -> MedicalDoc:
    doc = MedicalDoc(filename=filename, kind="RECEIPT")
    head = text.splitlines()[0]
    doc.fields["진료형태"] = "입원" if re.search(_CHECK + r"\s*입원", head) else "외래"
    _period(text, doc)
    m = re.search(r"요양기관\s*종류(.*)", text)
    if m:
        for key, kind in _FACILITY_KIND:
            if re.search(_CHECK + r"\s*" + key, m.group(1)):
                doc.fields["요양기관 종류"] = kind
                break
    m = re.search(r"상\s*호\s+(.+)", text)
    if m:
        doc.fields["의료기관"] = m.group(1).strip()
    for line in text.splitlines():
        t = _TOTAL_ROW.match(line.strip())
        if t:  # 합계: 본인부담금 공단부담금 전액본인부담 비급여
            nums = [_n(x) for x in t.group(1).split()]
            if len(nums) == 4:
                doc.fields["급여 본인부담 합계"] = str(nums[0])
                doc.fields["공단 부담 합계"] = str(nums[1])
                doc.fields["비급여 합계"] = str(nums[3])
                doc.fields["환자 부담 합계"] = str(nums[0] + nums[2] + nums[3])
                break
    codes = re.findall(rf"[주부]상병\s*:\s*({_KCD_TOKEN})", text)
    if codes:
        doc.fields["질병분류기호"] = codes[0]
        if codes[1:]:
            doc.fields["부상병"] = ", ".join(codes[1:])
    return doc


def _detail(filename: str, text: str) -> MedicalDoc:
    doc = MedicalDoc(filename=filename, kind="DETAIL")
    _period(text, doc)
    for n, raw in enumerate(text.splitlines(), 1):
        m = _DETAIL_ROW.match(raw.strip())
        if not m:
            continue
        nums = [_n(x) for x in m.group("nums").split()]
        _price, _times, days, total, copay, _insurer, full_copay, uncovered = nums
        name, date = m.group("name").strip(), m.group("date")
        common = {"doc": filename, "line": n, "date": date, "days": days, "code": m.group("code")}
        if copay or full_copay:  # 급여 (일부 본인부담 + 전액 본인부담)
            doc.items.append(Item(name, "covered", total - uncovered, copay + full_copay, **common))
        if uncovered:
            doc.items.append(Item(name, "uncovered", uncovered, uncovered, **common))
        if not (copay or full_copay or uncovered):  # 환자 부담 0원인 줄도 항목으로 남김
            doc.items.append(Item(name, "covered", total, 0, **common))
    return doc


def _diagnosis(filename: str, text: str) -> MedicalDoc:
    doc = MedicalDoc(filename=filename, kind="DIAGNOSIS")
    m = re.search(r"질병\s*분류\s*기호(.*?)(?:진단명|주상병)", text, re.DOTALL)
    codes = re.findall(_KCD_TOKEN, m.group(1)) if m else []
    if codes:
        # 주상병만 진단 코드로 씀. 부상병(전이 C77~C80 등)은 약관상 원발부위 기준이라 따로 둠
        doc.fields["질병분류기호"] = codes[0]
        if codes[1:]:
            doc.fields["부상병"] = ", ".join(codes[1:])
    for key, pattern in (
        ("진단일", r"진단일\s*(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일"),
        ("입원일", r"입원일\s*(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일"),
        ("퇴원일", r"퇴원일\s*(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일"),
        ("수술일", r"수술일\s*(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일"),
    ):
        d = re.search(pattern, text)
        if d:
            doc.fields[key] = f"{d.group(1)}-{int(d.group(2)):02d}-{int(d.group(3)):02d}"
    m = re.search(r"주상병\s*:\s*(.+)", text)
    if m:
        doc.fields["진단명"] = m.group(1).strip()
    m = re.search(r"병\s*기\s*:\s*(.+)", text)
    if m:
        doc.fields["병기"] = m.group(1).strip()
    m = re.search(r"최종\s*진단", text)
    if m:
        doc.fields["진단 구분"] = (
            "최종 진단" if re.search(_CHECK + r"\s*최종\s*진단", text) else "임상적 추정"
        )
    return doc


def parse_hospital_forms(filename: str, text: str) -> list[MedicalDoc]:
    """실제 병원 서식 묶음 → 서류 목록. 같은 파일의 서류는 filename 뒤에 순번을 붙임."""
    parts = split_documents(text)
    docs: list[MedicalDoc] = []
    for i, (kind, body) in enumerate(parts, 1):
        name = f"{filename} #{i}" if len(parts) > 1 else filename
        if kind == "RECEIPT":
            docs.append(_receipt(name, body))
        elif kind == "DETAIL":
            docs.append(_detail(name, body))
        elif kind == "DIAGNOSIS":
            docs.append(_diagnosis(name, body))
        else:  # 확인서·결과지: 종류만 구분 (내용은 AI 판단 입력으로 쓸 예정)
            docs.append(MedicalDoc(filename=name, kind=kind))
    return docs
