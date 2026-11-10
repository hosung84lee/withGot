"""진료 서류(영수증·세부내역서·진단서 등) 텍스트 → 청구 건.

지금 지원하는 서식은 `항목 | 값` 줄로 된 텍스트 서류입니다 (보장잇 시연 서류 `BOJANGIT SAMPLE V1 …`
와 같은 모양). 실제 병원 서식(표·스캔본)은 아직 읽지 못합니다.
"""

import re
from dataclasses import dataclass, field

KIND_LABEL = {
    "RECEIPT": "진료비 영수증",
    "DETAIL": "진료비 세부내역서",
    "DIAGNOSIS": "진단서",
    "PRESCRIPTION": "처방전",
    "PHARMACY": "약제비 영수증",
    "PAYMENT": "납입확인서",
    "UNKNOWN": "알 수 없는 서류",
}
# 제목으로 서류 종류 추정 (위에서부터 먼저 맞는 것)
_TITLE_HINTS = [
    ("세부산정내역", "DETAIL"),
    ("세부내역", "DETAIL"),
    ("약제비", "PHARMACY"),
    ("진료비 계산서", "RECEIPT"),
    ("영수증", "RECEIPT"),
    ("진단서", "DIAGNOSIS"),
    ("처방전", "PRESCRIPTION"),
    ("납입확인", "PAYMENT"),
]
_MARKER = re.compile(r"BOJANGIT SAMPLE V\d+ ([A-Z]+)")
_KCD = re.compile(r"^[A-Z]\d{2}(\.\d{1,2})?$")
BENEFIT = {"급여": "covered", "비급여": "uncovered"}
# 화면에 보이지 않게 할 개인정보 항목
PRIVATE_FIELDS = {"이름", "환자번호", "주민등록번호", "주소", "연락처"}


@dataclass
class Item:
    """청구 대상 의료비 한 줄."""

    name: str
    benefit: str  # covered | uncovered | unknown
    total: int
    patient: int  # 환자 부담
    doc: str  # 나온 서류 파일명
    line: int
    pharmacy: bool = False  # 약국 처방조제


@dataclass
class MedicalDoc:
    filename: str
    kind: str
    fields: dict[str, str] = field(default_factory=dict)
    items: list[Item] = field(default_factory=list)
    drugs: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return KIND_LABEL[self.kind]


@dataclass
class Claim:
    """한 진료 건에 대한 서류 묶음."""

    docs: list[MedicalDoc]
    case_id: str | None
    visit_date: str | None
    facility: str | None
    facility_type: str | None  # 상급종합병원 | 종합병원 | 병원 | 의원 | 약국 | None
    setting: str  # outpatient | hospitalization
    kcd: list[str]
    items: list[Item]
    warnings: list[str]


def _money(s: str) -> int | None:
    s = s.replace(",", "").replace("원", "").strip()
    return int(s) if s.isdigit() else None


def detect_kind(text: str) -> str:
    m = _MARKER.search(text)
    if m and m.group(1) in KIND_LABEL:
        return m.group(1)
    head = "\n".join(text.splitlines()[:5])
    for hint, kind in _TITLE_HINTS:
        if hint in head:
            return kind
    return "UNKNOWN"


def parse_document(filename: str, text: str) -> MedicalDoc:
    doc = MedicalDoc(filename=filename, kind=detect_kind(text))
    for n, raw in enumerate(text.splitlines(), 1):
        cells = [c.strip() for c in raw.split("|")]
        if len(cells) < 2:
            continue
        key = cells[0]
        if key == "치료" and len(cells) >= 5:
            total, patient = _money(cells[3]), _money(cells[4])
            if total is not None and patient is not None:
                benefit = BENEFIT.get(cells[2], "unknown")
                doc.items.append(Item(cells[1], benefit, total, patient, filename, n))
        elif key == "처방약":
            doc.drugs.append(" ".join(cells[1:]))
        elif key not in doc.fields:
            doc.fields[key] = " | ".join(cells[1:])
    if doc.kind == "PHARMACY":  # 약제비: 급여 본인부담·비급여를 항목으로
        for key, benefit in (("급여 본인부담", "covered"), ("비급여", "uncovered")):
            amount = _money(doc.fields.get(key, ""))
            if amount:
                doc.items.append(
                    Item(f"약제비 ({key})", benefit, amount, amount, filename, 0, pharmacy=True)
                )
    return doc


def facility_type(name: str | None) -> str | None:
    if not name:
        return None
    for key in ("상급종합병원", "종합병원", "요양병원", "치과병원", "한방병원"):
        if key in name:
            return "종합병원" if key == "종합병원" else key
    if "약국" in name:
        return "약국"
    if name.endswith("병원"):
        return "병원"
    if name.endswith(("의원", "보건소", "보건지소", "보건진료소")):
        return "의원"
    return None


def build_claim(docs: list[MedicalDoc]) -> Claim:
    warnings: list[str] = []
    cases = {d.fields["사례번호"] for d in docs if d.fields.get("사례번호")}
    if len(cases) > 1:
        warnings.append(f"서로 다른 진료 건의 서류가 섞여 있습니다: {', '.join(sorted(cases))}")

    def first(key: str) -> str | None:
        return next((d.fields[key] for d in docs if d.fields.get(key)), None)

    facility = first("의료기관")
    form = (first("진료형태") or first("입원/외래") or "").strip()
    setting = "hospitalization" if "입원" in form else "outpatient"

    kcd = []
    for d in docs:
        code = d.fields.get("질병분류기호", "").strip().upper()
        if code and _KCD.match(code):
            kcd.append(code)
        elif code:
            warnings.append(
                f"{d.filename}: 질병분류기호 `{code}` 는 KCD 형식이 아니라 확인하지 못했습니다."
            )

    # 세부내역서 항목이 기준. 없으면 다른 서류의 항목
    detail_items = [i for d in docs if d.kind == "DETAIL" for i in d.items]
    other_items = [i for d in docs if d.kind != "DETAIL" for i in d.items]
    items = detail_items + other_items

    receipt_total = next(
        (_money(d.fields.get("환자 부담 합계", "")) for d in docs if d.kind == "RECEIPT"), None
    )
    detail_total = sum(i.patient for i in detail_items)
    if receipt_total is not None and detail_items and receipt_total != detail_total:
        warnings.append(
            f"영수증 환자 부담 {receipt_total:,}원과 세부내역서 합계 {detail_total:,}원이 다릅니다."
        )
    if not detail_items and any(d.kind == "RECEIPT" for d in docs):
        warnings.append(
            "세부내역서가 없어 치료 항목별로 연결하지 못합니다. 세부내역서를 함께 올려 주세요."
        )

    return Claim(
        docs=docs,
        case_id=next(iter(cases)) if len(cases) == 1 else None,
        visit_date=first("진료일"),
        facility=facility,
        facility_type=facility_type(facility),
        setting=setting,
        kcd=kcd,
        items=items,
        warnings=warnings,
    )
