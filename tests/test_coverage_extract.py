"""약관 구조화 결과 → 사고보장 데이터 추출 테스트.

LLM 은 가짜 provider 로 바꿔서 API 키 없이 실행합니다.
fixtures/silson_mini.txt 는 실손 2605 약관 모양(보장종목별 제3조·제4조, 공통 제5조 한도,
제도성 특약)을 줄인 것이고, fixtures/silson_2605_disease_covered.json 은 실제 실손 2605
주계약 《질병급여형》을 사람이 원문과 대조해 만든 정답입니다.
"""

import json
from pathlib import Path

import pytest

from agent.providers import LLMProvider
from coverage_extract import build_bundles
from coverage_extract.__main__ import main as cli_main
from coverage_extract.compare import compare_products
from coverage_extract.extractor import ExtractionError, extract_coverage
from coverage_extract.grounding import ground_product, numbers_in
from schema.agent import LLMResponse
from schema.coverage import Product
from terms import parse_terms
from terms.extract import pdf_to_text

FIXTURES = Path(__file__).parent / "fixtures"
MINI_PATH = FIXTURES / "silson_mini.txt"
MINI = MINI_PATH.read_text(encoding="utf-8")
GOLDEN = FIXTURES / "silson_2605_disease_covered.json"
POLICIES = Path(__file__).parent.parent / "insurance-workbench" / "data" / "reference" / "policies"
PART = "테스트 급여 실손의료비보장보험(2605)(갱신형, 무배당) 약관"


class FakeProvider(LLMProvider):
    name = "openai"

    def __init__(self, replies):
        super().__init__("fake-model", 1000)
        self.replies = iter(replies)
        self.requests = []

    def build_request(self, system, messages, tools):
        return {"system": system, "messages": [m.content for m in messages]}

    def send(self, request):
        self.requests.append(request)
        return LLMResponse(
            text=next(self.replies), tool_calls=[], stop_reason="end", model="fake-model"
        )


@pytest.fixture(scope="module")
def doc():
    return parse_terms(MINI)


def src(article, paragraph=None, quote="", section="질병급여형"):
    return {
        "part": PART,
        "section": section,
        "article": article,
        "paragraph": paragraph,
        "quote": quote,
    }


def disease_reply(**override):
    """LLM 이 《질병급여형》 묶음에 돌려줄 법한 JSON (임시 id 사용)."""
    rule_in = {
        "id": "r1",
        "name": "급여 입원",
        "conditions": {
            "limit": {"amounts": [{"amount": 50000000, "per": "year", "selectable": True}]}
        },
        "benefit": {
            "type": "actual_cost",
            "base": "medical_cost",
            "cost_type": "covered",
            "ratio": {"numerator": override.get("ratio", 80), "denominator": 100},
        },
        "source": src("제3조", 1, override.get("quote", "본인부담금의 80%에 해당하는 금액")),
        "extra_sources": [src("제5조", 1, "5천만원 이내에서", section=None)],
        "status": "confirmed",  # LLM 이 confirmed 를 줘도 코드가 needs_review 로 되돌림
    }
    rule_out = {
        "id": "r2",
        "name": "급여 통원",
        "conditions": {
            "limit": {"amounts": [{"amount": 200000, "per": "visit", "selectable": True}]}
        },
        "benefit": {
            "type": "actual_cost",
            "cost_type": "covered",
            "base": "medical_cost",
            "deductible": {"amounts": [10000], "ratios": [{"numerator": 20, "denominator": 100}]},
        },
        "source": src(
            override.get("article", "제3조"),
            1,
            "1 만원, 보장대상 의료비의 20% 중 큰 금액을 뺀 금액",
        ),
        "extra_sources": [src("제5조", 2, "통원 1회당 20만원 이내에서", section=None)],
    }
    return json.dumps(
        {
            "risks": [
                {
                    "id": "a",
                    "claim_reason": "hospitalization",
                    "section": "질병급여형",
                    "rules": [rule_in],
                },
                {
                    "id": "b",
                    "claim_reason": "outpatient",
                    "section": "질병급여형",
                    "rules": [rule_out],
                },
            ],
            "exclusions": [
                {
                    "id": "x1",
                    "kind": "kcd",
                    "description": "요실금",
                    "coverage_code": "URINARY",
                    "source": src("제4조", 2, "요실금(N39.3, N39.4, R32)"),
                },
                {
                    "id": "x2",
                    "kind": "cause",
                    "description": "고의 자해",
                    "source": src("제4조", 1, "피보험자가 고의로 자신을 해친 경우"),
                },
            ],
            "coverage_codes": [
                {
                    "code": "URINARY",
                    "name": "요실금",
                    "kcd": [{"start": "N39.3", "end": "N39.4"}, {"start": "R32", "end": "R32"}],
                    "source": src("제4조", 2, "요실금(N39.3, N39.4, R32)"),
                }
            ],
        },
        ensure_ascii=False,
    )


INJURY_REPLY = json.dumps(
    {
        "risks": [
            {
                "id": "a",
                "claim_reason": "hospitalization",
                "section": "상해급여형",
                "rules": [
                    {
                        "id": "r1",
                        "name": "급여 입원",
                        "benefit": {
                            "type": "actual_cost",
                            "cost_type": "covered",
                            "ratio": {"numerator": 80},
                        },
                        "source": src(
                            "제3조", 1, "본인부담금의 80%에 해당하는 금액", section="상해급여형"
                        ),
                    }
                ],
            }
        ]
    },
    ensure_ascii=False,
)


# ---------------------------------------------------------------- 추출 묶음


def test_bundles_by_section(doc):
    bundles = build_bundles(doc)
    assert [(b.kind, b.section) for b in bundles] == [
        ("main", "질병급여형"),
        ("main", "상해급여형"),
    ]
    disease = bundles[0]
    # 보장종목 조 + 제3조가 인용한 공통 제5조(한도). 보험금 청구(제6조)·제도성 특약은 빠짐
    assert [a.label for a in disease.articles] == ["제3조", "제4조", "제5조"]
    body = disease.render()
    assert body.startswith(f"약관: {PART}\n\n보장종목: 질병급여형")
    assert (
        "### 제3조 (보상내용) 《질병급여형》" in body and "### 제5조 (보험가입금액 한도 등)" in body
    )
    assert "지정대리청구인" not in body


def test_no_bundles_for_non_benefit_terms():
    doc = parse_terms(
        "제1조(목적)\n이 약관은 서비스 이용 조건을 정합니다.\n제2조(정의)\n용어를 정의합니다."
    )
    assert build_bundles(doc) == []
    with pytest.raises(ExtractionError):
        extract_coverage(doc, provider=FakeProvider([]))


# ---------------------------------------------------------------- 근거 검증


def test_numbers_in_korean_amounts():
    found = numbers_in(
        "연간 5천\n만원 이내, 통원 1회당 20 만원, 공제 1 만원, 상한 200만원, 80% 보상, 180일, 최대 90회"
    )
    assert {50_000_000, 200_000, 10_000, 2_000_000} <= found["amount"]
    assert found["percent"] == {80} and found["days"] == {180} and found["count"] == {1, 90}


def _grounded(doc, reply):
    return extract_coverage(doc, provider=FakeProvider([reply]), sections=["질병급여형"])


def test_extraction_grounded_and_ids_reassigned(doc):
    report = _grounded(doc, disease_reply())
    assert report.issues == []
    p = report.product
    assert [c.name for c in p.coverages] == [PART]
    ids = [r.id for r in p.rules()] + [e.id for e in p.exclusions()]
    assert ids == [
        "p0/질병급여형/hospitalization1/1",
        "p0/질병급여형/outpatient2/1",
        "p0/질병급여형/exclusion1",
        "p0/질병급여형/exclusion2",
    ]
    # 담보코드도 묶음 기준으로 바뀌고 보상 제외가 그 코드를 가리킴
    assert p.coverage_codes[0].code == "p0/질병급여형/URINARY"
    assert p.exclusions()[0].coverage_code == "p0/질병급여형/URINARY"
    assert {x.status for x in [*p.rules(), *p.exclusions()]} == {"confirmed"}


def test_quote_not_in_source_needs_review(doc):
    report = _grounded(doc, disease_reply(quote="본인부담금의 90%를 보상"))
    rule = report.product.rules()[0]
    assert rule.status == "needs_review"
    assert [i.code for i in report.issues] == ["QUOTE_NOT_FOUND"]


def test_number_not_in_source_needs_review(doc):
    # 원문은 80% 인데 LLM 이 90% 로 잘못 읽은 경우
    report = _grounded(doc, disease_reply(ratio=90))
    assert [(i.code, i.target) for i in report.issues] == [
        ("NUMBER_NOT_FOUND", "p0/질병급여형/hospitalization1/1")
    ]
    assert "보상률 90" in report.issues[0].message


def test_missing_article_is_error(doc):
    report = _grounded(doc, disease_reply(article="제9조"))
    assert [(i.severity, i.code) for i in report.issues] == [("error", "SOURCE_NOT_FOUND")]
    assert report.product.rules()[1].status == "needs_review"


def test_extract_all_sections_one_request_each(doc):
    provider = FakeProvider([disease_reply(), INJURY_REPLY])
    report = extract_coverage(doc, provider=provider)
    assert len(provider.requests) == 2
    assert "보장종목: 상해급여형" in provider.requests[1]["messages"][0]
    assert [r.id for r in report.product.rules()][-1] == "p0/상해급여형/hospitalization1/1"
    assert report.needs_review == 0


def test_invalid_json_is_retried(doc):
    provider = FakeProvider(["설명부터 할게요 {not json", disease_reply()])
    report = extract_coverage(doc, provider=provider, sections=["질병급여형"])
    assert len(provider.requests) == 2 and report.confirmed == 4


# ---------------------------------------------------------------- 정답 비교


def test_compare_with_golden(doc):
    golden = _grounded(doc, disease_reply()).product
    # 같은 내용이면 id·인용문이 달라도 모두 일치
    same = _grounded(doc, disease_reply(quote="본인부담금의 80%에 해당하는 금액")).product
    result = compare_products(same, golden)
    assert result.score == 1.0 and not result.different and not result.missing

    # 보상률을 잘못 뽑으면 '값이 다름', 통원 규칙을 빠뜨리면 '빠짐'
    wrong = _grounded(doc, disease_reply(ratio=90)).product
    wrong.coverages[0].risks = wrong.coverages[0].risks[:1]
    result = compare_products(wrong, golden)
    assert result.different == ["질병급여형 급여 입원 — 보상률: 0.9 (정답 0.8)"]
    assert result.missing == ["질병급여형 급여 통원"]
    assert result.score == pytest.approx(2 / 4)  # 일치: 보상 제외 2건 / 정답 규칙 2 + 제외 2


def test_cli_ground_and_compare(tmp_path, capsys, doc):
    out = tmp_path / "out.json"
    golden = _grounded(doc, disease_reply()).product
    out.write_text(
        json.dumps({"product": golden.model_dump(), "issues": []}, ensure_ascii=False), "utf-8"
    )
    assert cli_main([str(MINI_PATH), "--ground", str(out), "--compare", str(out)]) == 0
    text = capsys.readouterr().out
    assert "근거 확인 4건 · 검토 필요 0건" in text and "값까지 일치 100%" in text


# ---------------------------------------------------------------- 명령


def test_cli_dry_run(capsys):
    assert cli_main([str(MINI_PATH), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "[main]" in out and "질병급여형" in out and "상해급여형" in out


# ---------------------------------------------------------------- 실제 약관 PDF (pytest --pdf)


@pytest.mark.pdf
def test_real_silson_2605_golden_is_grounded():
    pdf = next(POLICIES.glob("삼성생명_급여실손의료비보장보험_2605*.pdf"), None)
    if pdf is None:
        pytest.skip("실손 2605 약관 PDF 없음")
    doc = parse_terms(pdf_to_text(pdf))
    golden = Product.model_validate_json(GOLDEN.read_text(encoding="utf-8"))
    report = ground_product(golden, doc)
    assert report.issues == []
    assert report.confirmed == len(golden.rules()) + len(golden.exclusions()) == 11
    keys = [b.key for b in build_bundles(doc)]
    assert len(keys) == 8 and keys[0].endswith("질병급여형")
