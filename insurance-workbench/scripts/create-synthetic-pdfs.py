"""Generate supported-format demo or validation PDFs with synthetic data."""

import argparse
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "apps/web/public/samples"
VALIDATION = ROOT / "data/synthetic/medical-bills"
FONT = Path("C:/Windows/Fonts/malgun.ttf")


def create_document(filename, title, signature, rows, *, case="DEMO-001", continuation=()):
    pdf = Canvas(str(filename), pagesize=(595, 842), invariant=1)
    pdf.setTitle(title + " - 가상 데이터")
    pdf.setAuthor("Bojangit synthetic sample")
    pages = [[signature, f"사례번호 | {case}", "이름 | 가상 김하늘",
              "환자번호 | PRIVATE-PATIENT-TRACE-48291", *rows], *continuation]
    for index, page_rows in enumerate(pages, start=1):
        pdf.setFillColor(HexColor("#edf5ef"))
        pdf.rect(0, 730, 595, 112, fill=1, stroke=0)
        pdf.setFillColor(HexColor("#275a3b"))
        pdf.setFont("Korean", 22)
        pdf.drawString(42, 785, title)
        pdf.setFont("Korean", 10)
        pdf.drawString(42, 753, "보장잇 개인정보 보호 시연용 가상 서류")
        pdf.setFillColor(HexColor("#344b3d"))
        pdf.setFont("Korean", 11)
        for row_index, row in enumerate(page_rows):
            pdf.drawString(42, 695 - row_index * 35, row)
        pdf.setStrokeColor(HexColor("#d3dfd5"))
        pdf.line(42, 106, 553, 106)
        pdf.setFont("Korean", 9)
        pdf.setFillColor(HexColor("#64766a"))
        pdf.drawString(42, 82, "모든 인물과 진료 내역은 가상입니다. 제출용으로 사용할 수 없습니다.")
        pdf.drawRightString(553, 35, f"{index} / {len(pages)}")
        pdf.showPage()
    pdf.save()


def create_validation_pairs():
    VALIDATION.mkdir(parents=True, exist_ok=True)
    cases = [
        ("covered-visit", "DEMO-002", 60_000, 42_000, 18_000, [
            "치료 | 외래 진찰료 | 급여 | 20000 | 6000",
            "치료 | 혈액 검사 | 급여 | 40000 | 12000",
        ], ()),
        ("multipage", "DEMO-003", 377_000, 32_900, 344_100, [
            "치료 | 외래 진찰료 | 급여 | 22000 | 6600",
            "치료 | 혈액 검사 | 급여 | 25000 | 7500",
        ], (["치료 | 복부 MRI | 비급여 | 300000 | 300000",
             "치료 | 영양 주사 | 비급여 | 30000 | 30000"],)),
        ("amount-mismatch", "DEMO-004", 50_000, 30_000, 20_000, [
            "치료 | 외래 진찰료 | 급여 | 20000 | 6000",
            "치료 | 혈액 검사 | 급여 | 30000 | 13000",
        ], ()),
    ]
    for slug, case, total, insurer, patient, rows, continuation in cases:
        create_document(VALIDATION / f"{slug}-receipt.pdf", "진료비 계산서·영수증",
                        "BOJANGIT SAMPLE V1 RECEIPT", [f"진료비 총액 | {total}",
                        f"공단 부담 | {insurer}", f"환자 부담 합계 | {patient}"], case=case)
        count = len(rows) + sum(map(len, continuation))
        create_document(VALIDATION / f"{slug}-details.pdf", "진료비 세부산정내역서",
                        "BOJANGIT SAMPLE V1 DETAIL", [f"항목 수 | {count}",
                        "치료 항목은 종류 · 급여 구분 · 총액 · 환자 부담 순서입니다.", *rows],
                        case=case, continuation=continuation)


def create_supplements():
    folder = OUTPUT / "supplements"
    folder.mkdir(parents=True, exist_ok=True)
    documents = [
        ("diagnosis", "진단서", "DIAGNOSIS", [
            "문서번호 | DX-001", "진단명 | 시연용 진단", "질병분류기호 | DEMO-DX-01",
        ]),
        ("prescription", "처방전", "PRESCRIPTION", [
            "문서번호 | RX-001", "처방약 | 가상 처방약 A | 3", "처방약 | 가상 처방약 B | 5",
        ]),
        ("payment", "납입확인서", "PAYMENT", [
            "문서번호 | PAY-001", "납입 범위 | 해당 진료 건", "납입액 | 563150",
        ]),
        ("pharmacy", "약제비 계산서·영수증", "PHARMACY", [
            "문서번호 | PH-001", "처방번호 | RX-001", "급여 본인부담 | 10000", "비급여 | 2400",
            "약국 환자 부담 합계 | 12400",
        ]),
    ]
    for name, title, kind, rows in documents:
        create_document(folder / f"{name}.pdf", title, f"BOJANGIT SAMPLE V1 {kind}", rows)


def create_claim_routing_cases():
    folder = ROOT / "data/synthetic/claim-routing"
    folder.mkdir(parents=True, exist_ok=True)
    for name, code, label in [
        ("c44-diagnosis", "C44.9", "가상 기타피부암 분류 확인"),
        ("c50-diagnosis", "C50.9", "가상 일반암 분류 확인"),
    ]:
        create_document(folder / f"{name}.pdf", "진단서", "BOJANGIT SAMPLE V1 DIAGNOSIS", [
            f"문서번호 | {name}", f"진단명 | {label}", f"질병분류기호 | {code}",
        ])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font", type=Path, default=FONT)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--validation", action="store_true")
    mode.add_argument("--supplements", action="store_true")
    mode.add_argument("--claim-routing", action="store_true")
    args = parser.parse_args()
    FONT = args.font
    if not FONT.exists():
        raise SystemExit("Set FONT to an installed Korean TrueType font before generating samples.")
    pdfmetrics.registerFont(TTFont("Korean", str(FONT)))
    if args.claim_routing:
        create_claim_routing_cases()
        print("Created two synthetic diagnosis PDFs in data/synthetic/claim-routing")
        raise SystemExit(0)
    if args.supplements:
        create_supplements()
        print("Created four supporting PDFs in apps/web/public/samples/supplements")
        raise SystemExit(0)
    if args.validation:
        create_validation_pairs()
        print("Created six synthetic validation PDFs in data/synthetic/medical-bills")
        raise SystemExit(0)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    create_document(OUTPUT / "receipt.pdf", "진료비 계산서·영수증", "BOJANGIT SAMPLE V1 RECEIPT", [
        "진료일 | 2026-11-02", "의료기관 | 가상한빛의원",
        "진료비 총액 | 605500", "공단 부담 | 42350", "환자 부담 합계 | 563150",
    ])
    create_document(OUTPUT / "details.pdf", "진료비 세부산정내역서", "BOJANGIT SAMPLE V1 DETAIL", [
        "항목 수 | 4", "치료 항목은 종류 · 급여 구분 · 총액 · 환자 부담 순서입니다.",
        "치료 | 외래 진찰료 | 급여 | 18500 | 5550",
        "치료 | 혈액 검사 | 급여 | 42000 | 12600",
        "치료 | 복부 MRI | 비급여 | 480000 | 480000",
        "치료 | 영양 주사 | 비급여 | 65000 | 65000",
        "환자 부담 합계 | 563150",
    ])
    print("Created two synthetic PDFs in apps/web/public/samples")
