"""스키마 갭 분석 테스트: 약관에 있는데 사고보장 데이터로 담지 못한 것을 찾는지."""

from pathlib import Path

import pytest

from coverage_extract.__main__ import main as cli_main
from coverage_extract.gaps import CONCEPTS, analyze_gaps, format_report
from schema.coverage import Product
from terms import parse_terms
from terms.extract import pdf_to_text

FIXTURES = Path(__file__).parent / "fixtures"
POLICIES = Path(__file__).parent.parent / "insurance-workbench" / "data" / "reference" / "policies"
PART = "테스트 급여 실손의료비보장보험(2605)(갱신형, 무배당) 약관"

# silson_mini.txt 에 실제 실손 약관 문장을 몇 개 끼워 넣음
TEXT = (
    (FIXTURES / "silson_mini.txt")
    .read_text(encoding="utf-8")
    .replace(
        "② 피보험자가 건강보험을 적용받지 못하는 경우에는 의료비의 40%를 보상합니다.\n",
        "② 피보험자가 건강보험을 적용받지 못하는 경우에는 의료비의 40%를 보상합니다.\n"
        "③ 피보험자가 입원하여 치료를 받던 중 보험계약이 종료되더라도 그 계속 중인 입원에 대해서는"
        " 보험계약 종료일 다음날부터 180일까지 보상합니다.\n"
        "④ 하나의 질병으로 동일한 의료기관에서 같은 날 외래 및 처방을 함께 받은 경우 통원 1회로 보아"
        " 제1항을 적용합니다.\n"
        "⑤ “하나의 질병”이란 발생 원인이 동일한 질병을 말합니다.\n",
        1,
    )
    .replace(
        "상해로 입원한 경우 본인부담금의 80%",
        "상해로 입원한 경우 제5조(보험가입금액 한도 등)에서 정한 한도 내에서 본인부담금의 80%",
        1,
    )
    .replace(
        "1. 요실금(N39.3, N39.4, R32)\n",
        "1. 요실금(N39.3, N39.4, R32)\n"
        "2. 선천성 뇌질환(Q00∼Q04) (다만, 피보험자가 보험가입당시 태아인 경우에는 보상합니다.)\n"
        "3. 성장호르몬제 투여에 소요된 비용으로 부담한 전액본인부담금\n",
        1,
    )
    .replace(
        "② 통원의 경우 통원 1회당 20만원",
        "③ 이 계약에서 ‘연간’이라 함은 계약일로부터 매1년 단위로 도래하는 계약해당일 전일까지의"
        " 기간을 말합니다.\n② 통원의 경우 통원 1회당 20만원",
        1,
    )
)


def src(article, paragraph=None, quote="", section="질병급여형"):
    return {
        "part": PART,
        "section": section,
        "article": article,
        "paragraph": paragraph,
        "quote": quote,
    }


def product() -> Product:
    """입원 규칙(연장 180일 값은 있으나 제3조③ 인용 없음)과 요실금 제외만 있는 데이터."""
    return Product.model_validate(
        {
            "name": PART,
            "coverages": [
                {
                    "id": "p0",
                    "name": PART,
                    "kind": "main",
                    "risks": [
                        {
                            "id": "p0/질병급여형/hospitalization1",
                            "claim_reason": "hospitalization",
                            "section": "질병급여형",
                            "rules": [
                                {
                                    "id": "p0/질병급여형/hospitalization1/1",
                                    "name": "급여 입원",
                                    "conditions": {"extension": {"days": 180}},
                                    "benefit": {
                                        "type": "actual_cost",
                                        "base": "medical_cost",
                                        "ratio": {"numerator": 80},
                                    },
                                    "source": src("제3조", 1, "본인부담금의 80%에 해당하는 금액"),
                                }
                            ],
                        }
                    ],
                    "exclusions": [
                        {
                            "id": "p0/질병급여형/exclusion1",
                            "kind": "kcd",
                            "description": "요실금",
                            "coverage_code": "URINARY",
                            "section": "질병급여형",
                            "source": src("제4조", 2, "요실금(N39.3, N39.4, R32)"),
                        },
                    ],
                }
            ],
            "coverage_codes": [
                {
                    "code": "URINARY",
                    "name": "요실금",
                    "kcd": [{"start": "N39.3", "end": "N39.4"}, {"start": "R32", "end": "R32"}],
                }
            ],
        }
    )


@pytest.fixture(scope="module")
def doc():
    return parse_terms(TEXT)


def codes(report) -> set[str]:
    return {f.concept.code for f in report.findings}


def test_concepts_found_without_data(doc):
    report = analyze_gaps(doc)
    assert {
        "SHARED_LIMIT",
        "COUNTING_RULE",
        "EVENT_DEFINITION",
        "PERIOD_BASIS",
        "INSURED_CONDITION",
        "STRUCTURED_EXCEPTION",
    } <= codes(report)
    assert "STAGED_LIMIT" not in codes(report)  # 원문에 없는 개념은 안 나옴
    assert report.coverage == [] and report.uncovered == []  # 데이터 없이는 1번만


def test_common_article_reported_once(doc):
    """공통 제5조는 두 보장종목 묶음에 모두 들어가지만 한 번만 보고하고 묶음을 모두 기록."""
    shared = next(f for f in analyze_gaps(doc).findings if f.concept.code == "SHARED_LIMIT")
    assert len(shared.hits) == 1
    hit = shared.hits[0]
    assert hit.unit.article == "제5조" and hit.unit.paragraph == 1
    assert len(hit.bundles) == 2
    assert "합산하여 5천" in hit.snippet


def test_exclusion_only_concept_limited_to_exclusion_article(doc):
    exc = next(f for f in analyze_gaps(doc).findings if f.concept.code == "STRUCTURED_EXCEPTION")
    assert {h.unit.article for h in exc.hits} == {"제4조"}


def test_uncovered_reasons(doc):
    report = analyze_gaps(doc, product())
    by_label = {x.unit.label: x for x in report.uncovered}
    cov = report.coverage[0]
    assert cov.bundle.endswith("질병급여형")
    assert cov.cited == 2  # 제3조①(입원 80%), 제4조② 1.(요실금)
    # 안내 문장('회사는 다음의 … 보상하지 않습니다')은 세지 않음
    assert "제4조 ①" not in by_label and "제4조 ②" not in by_label
    # 스키마에 자리가 없어 빠짐
    assert by_label["제3조 ④"].reason == "schema_gap"
    assert by_label["제3조 ④"].concepts == ["COUNTING_RULE"]
    assert by_label["제3조 ⑤"].concepts == ["EVENT_DEFINITION"]
    # 값(180일)은 데이터에 있는데 이 항을 근거로 인용하지 않음
    assert by_label["제3조 ③"].reason == "uncited_value"
    assert by_label["제3조 ③"].values == ["연장 보상 일수 180"]
    # 지금 스키마(Exclusion cost_item)로 담을 수 있는데 데이터에서 빠짐
    assert by_label["제4조 ② 3."].reason == "extraction_gap"
    # '가입 당시 태아' 예외는 피보험자 조건(필드 추가) → 스키마 갭
    assert by_label["제4조 ② 2."].reason == "schema_gap"
    assert set(by_label["제4조 ② 2."].concepts) == {"STRUCTURED_EXCEPTION", "INSURED_CONDITION"}


def test_concept_catalog_is_complete():
    for c in CONCEPTS:
        assert c.patterns and c.now and c.proposal
    assert len({c.code for c in CONCEPTS}) == len(CONCEPTS)


def test_format_and_cli(tmp_path, capsys, doc):
    text = format_report(analyze_gaps(doc, product()))
    assert "[구조 확장] 1회 산정 규칙" in text and "스키마에 자리가 없어 빠짐" in text
    terms = tmp_path / "t.txt"
    terms.write_text(TEXT, encoding="utf-8")
    data = tmp_path / "p.json"
    data.write_text(product().model_dump_json(), encoding="utf-8")
    out = tmp_path / "gaps.json"
    assert cli_main([str(terms), "--gaps", "--ground", str(data), "--out", str(out)]) == 0
    assert "근거 없는 원문" in capsys.readouterr().out
    assert '"findings"' in out.read_text(encoding="utf-8")


# ---------------------------------------------------------------- 실제 약관 PDF (pytest --pdf)


@pytest.mark.pdf
def test_real_silson_2605_gaps():
    pdf = next(POLICIES.glob("삼성생명_급여실손의료비보장보험_2605*.pdf"), None)
    if pdf is None:
        pytest.skip("실손 2605 약관 PDF 없음")
    golden = Product.model_validate_json(
        (FIXTURES / "silson_2605_disease_covered.json").read_text(encoding="utf-8")
    )
    report = analyze_gaps(parse_terms(pdf_to_text(pdf)), golden)
    assert len(report.findings) == 16 and len(CONCEPTS) == 26  # 실손 16종 + 정액형 10종
    assert [(c.units, c.cited) for c in report.coverage] == [(36, 12)]
    reasons = [x.reason for x in report.uncovered]
    assert (
        reasons.count("schema_gap"),
        reasons.count("uncited_value"),
        reasons.count("extraction_gap"),
    ) == (8, 2, 14)
    assert [u.concept for u in report.unfilled] == ["KCD_VERSION"]
