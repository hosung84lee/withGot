"""진료 서류(영수증·세부내역서·진단서 등) 텍스트 → 청구 건.

지원하는 서식
- `항목 | 값` 줄로 된 텍스트 서류 (보장잇 시연 서류 `BOJANGIT SAMPLE V1 …`) → parse_document
- 실제 병원 서식 (진료비 계산서·영수증, 세부산정내역, 진단서 등. 한 PDF 에 여러 서류 묶음 가능)
  → hospital_forms.parse_hospital_forms. parse_documents 가 서식을 보고 알맞은 쪽을 고릅니다.
스캔본·사진은 글자가 없어 읽지 못합니다.
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
    "ADMISSION": "입·퇴원 확인서",
    "PATHOLOGY": "병리검사 결과지",
    "RADIATION": "방사선치료 확인서",
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
    benefit: str  # covered | uncovered | unknown | diagnosis (진단서 질병코드)
    total: int
    patient: int  # 환자 부담
    doc: str  # 나온 서류 파일명
    line: int
    pharmacy: bool = False  # 약국 처방조제
    date: str | None = None  # 세부산정내역의 일자 ('07.06', '07.06~08.06')
    days: int = 1  # 세부산정내역의 일수 (여러 날 합산이면 > 1)
    code: str | None = None  # 수가·EDI 코드


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


def parse_documents(filename: str, text: str) -> list[MedicalDoc]:
    """파일 하나의 텍스트 → 서류 목록. 실제 병원 서식 묶음이면 서류별로 나눠 읽음."""
    from .hospital_forms import is_hospital_form, parse_hospital_forms

    if not _MARKER.search(text) and is_hospital_form(text):
        return parse_hospital_forms(filename, text)
    return [parse_document(filename, text)]


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

    # 영수증에 주상병이 적혀 있으면 그 진료 건의 코드로 씀 (다른 진료 건의 진단서와 섞이지 않게)
    own = [d for d in docs if d.kind == "RECEIPT" and d.fields.get("질병분류기호")]
    kcd = []
    for d in own or docs:
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
    multi = [i for i in detail_items if i.days > 1 or "~" in (i.date or "")]
    if setting == "outpatient" and multi:
        warnings.append(
            "여러 날 통원이 한 영수증에 합쳐져 있습니다. 통원 공제는 방문 1회마다 적용되므로 "
            "아래 참고 계산(합산 기준)은 실제와 다를 수 있습니다. 방문일별 계산은 아직 지원하지 않습니다."
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
        facility_type=first("요양기관 종류") or facility_type(facility),
        setting=setting,
        kcd=kcd,
        items=items,
        warnings=warnings,
    )


def build_claims(docs: list[MedicalDoc]) -> list[Claim]:
    """서류 묶음 → 진료 건 목록.

    실제 서식은 한 번에 여러 진료 건(외래 영수증 + 입원 영수증 …)이 올라올 수 있어, 영수증마다
    진료기간이 같은 세부산정내역과 짝지어 진료 건 하나로 만듭니다. 진단서·확인서 등 나머지 서류는
    모든 진료 건에 함께 붙입니다. 영수증이 하나 이하면 전체가 진료 건 하나.
    """
    receipts = [d for d in docs if d.kind == "RECEIPT"]
    if len(receipts) <= 1:
        return [build_claim(docs)]
    shared = [d for d in docs if d.kind not in ("RECEIPT", "DETAIL")]
    details = [d for d in docs if d.kind == "DETAIL"]
    used: set[int] = set()
    claims = []
    for r in receipts:
        period = r.fields.get("진료기간")
        mine = [
            d
            for d in details
            if id(d) not in used and period and d.fields.get("진료기간") == period
        ][:1]
        used.update(id(d) for d in mine)
        claims.append(build_claim([r, *mine, *shared]))
    return claims


def claim_label(claim: Claim) -> str:
    """진료 건을 고르는 목록에 보일 이름."""
    receipt = next((d for d in claim.docs if d.kind == "RECEIPT"), None)
    period = (receipt.fields.get("진료기간") if receipt else None) or claim.visit_date or ""
    setting = "입원" if claim.setting == "hospitalization" else "통원"
    return " · ".join(x for x in (setting, claim.facility, period) if x)
