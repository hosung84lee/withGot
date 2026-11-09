"""보험사 약관 PDF 모양(목차·안내 페이지, 주계약+특약 묶음, 부록 법령)에 대한 구조화 테스트.

fixtures/insurance_bundle.txt 는 저장소의 실제 삼성생명 약관 PDF 에서 뽑은 텍스트 모양을
줄여서 옮긴 것입니다. 실제 PDF 테스트는 insurance-workbench 의 약관 파일이 있을 때만 돕니다.
"""

from collections import Counter
from pathlib import Path

import pytest

from terms import parse_terms, validate_structure
from terms.extract import pdf_to_text

BUNDLE = (Path(__file__).parent / "fixtures" / "insurance_bundle.txt").read_text(encoding="utf-8")
POLICIES = Path(__file__).parent.parent / "insurance-workbench" / "data" / "reference" / "policies"


@pytest.fixture(scope="module")
def bundle():
    return parse_terms(BUNDLE)


def codes(issues):
    return Counter(i.code for i in issues)


# ---------------------------------------------------------------- 목차·안내 페이지


def test_toc_lines_are_not_articles(bundle):
    # 목차의 '제 1 조 [보장종목] 5' 같은 줄은 조가 되지 않고, 본문의 조만 남음
    main = [a for a in bundle.articles if a.part == 0]
    assert [a.label for a in main] == ["제1조", "제2조", "제3조", "제4조", "제4조의2", "제5조"]
    assert all(a.line > 30 for a in bundle.articles)  # 목차·안내 페이지(30줄 이전)의 조 없음
    assert bundle.find("제1조").full_text().startswith("회사가 판매하는")


def test_guide_page_articles_dropped(bundle):
    # 안내 페이지의 '제3조(보상내용)' 는 뒤의 본문 조와 번호·제목이 같아서 지워짐
    assert [a for a in bundle.articles if a.part is None] == []


def test_toc_appendix_line_does_not_swallow_body(bundle):
    # 목차의 '[별표 2] … 38' 이 별표로 시작되면 본문 전체가 별표에 들어가던 문제
    assert [x.label for x in bundle.appendices if x.label.startswith("별표")] == [
        "별표 1 용어의 정의"
    ]
    assert "보상합니다" not in bundle.appendices[0].text


def test_toc_headings_dropped(bundle):
    main = [h.label for h in bundle.headings if h.part == 0]
    assert main == ["제1관 일반사항", "제2관 보상하는 사항", "제3관 계약의 성립"]
    assert all(h.part is not None for h in bundle.headings)


def test_title_split_over_two_lines(bundle):
    a = bundle.find("제4조의2")
    assert a.title == "‘기본형 실손의료비보장보험’에서 보상하지 않는 사항"
    assert "제4조제1항제2호" in a.full_text()
    # 이어진 제목 줄이 앞 조(제4조)의 본문으로 붙지 않음
    assert "보상하지 않는 사항]" not in bundle.find("제4조").full_text()


# ---------------------------------------------------------------- 주계약 + 특약 묶음


def test_parts_split_main_and_rider(bundle):
    assert [p.title for p in bundle.parts] == [
        "테스트 급여 실손의료비보장보험(2605)(갱신형, 무배당) 약관",
        "지정대리청구서비스특약 약관",
    ]
    rider = [a for a in bundle.articles if a.part == 1]
    assert [(a.label, a.title) for a in rider] == [
        ("제1조", "적용 대상"),
        ("제2조", "지정대리청구인의 지정"),
    ]
    assert rider[0].path == ["제1관 보험계약의 성립과 유지"]


def test_appendix_closes_when_rider_starts(bundle):
    # 주계약 별표 뒤에 이어지는 특약 본문이 별표에 들어가지 않음
    assert "지정대리청구인" not in bundle.appendices[0].text


def test_annex_laws_are_not_articles(bundle):
    # 부록의 법령 조문 ('제 2 조(정의)')은 조로 구조화하지 않고 원문 그대로 보관
    annex = [x for x in bundle.appendices if x.label.startswith("부록")]
    assert len(annex) == 1 and "의사 등의 신고" in annex[0].text
    assert not any(a.title in ("정의", "의사 등의 신고") for a in bundle.articles)


def test_validation_per_part(bundle):
    found = codes(validate_structure(bundle))
    # 특약의 제1조는 주계약 제1조와 다른 약관이라 중복·순서 문제가 아님
    for code in ("ARTICLE_DUPLICATE", "ARTICLE_ORDER", "ARTICLE_NUMBER_GAP", "HEADING_NUMBER_GAP"):
        assert found[code] == 0, code
    assert found["BROKEN_REFERENCE"] == 0


def test_rider_reference_resolves_within_part(bundle):
    # 특약 제2조의 '제1조' 는 특약 제1조를 가리킴 (주계약 제1조가 아니라)
    rider2 = next(a for a in bundle.articles if a.part == 1 and a.number == 2)
    assert [r.article_label for r in rider2.references] == ["제1조"]


def test_part_without_articles_is_reported():
    text = BUNDLE.replace("제 1 조 [적용 대상]", "제1-1조 [적용 대상]").replace(
        "제 2 조 [지정대리청구인의 지정]", "제1-2조 [지정대리청구인의 지정]"
    )
    doc = parse_terms(text)
    issues = [i for i in validate_structure(doc) if i.code == "PART_WITHOUT_ARTICLES"]
    assert [i.article for i in issues] == ["지정대리청구서비스특약 약관"]


def test_plain_terms_without_parts_unchanged():
    # 약관 제목 줄이 없는 일반 약관은 part 없이 그대로
    doc = parse_terms("제1조(목적)\n본문\n제2조(정의)\n① 정의 본문")
    assert doc.parts == [] and [a.part for a in doc.articles] == [None, None]


# ---------------------------------------------------------------- 실제 약관 PDF


def _real(name: str):
    path = next(POLICIES.glob(f"{name}*.pdf"), None)
    if path is None:
        pytest.skip(f"약관 PDF 없음: {name}")
    return parse_terms(pdf_to_text(path))


@pytest.fixture(scope="module")
def silson_2605():
    return _real("삼성생명_급여실손의료비보장보험_2605")


def _article_line_share(doc, total_lines: int) -> float:
    """원문 줄 가운데 조 구간이 차지하는 비율."""
    marks = sorted(
        [(a.line, "a") for a in doc.articles]
        + [(h.line, "h") for h in doc.headings]
        + [(x.line, "x") for x in doc.appendices]
    )
    owned = 0
    for i, (line, kind) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else total_lines + 1
        if kind == "a":
            owned += end - line
    return owned / total_lines


def test_real_silson_2605_structure(silson_2605):
    doc = silson_2605
    titles = [p.title for p in doc.parts]
    assert titles[0] == "삼성 급여 실손의료비보장보험(2605)(갱신형, 무배당) 약관"
    assert "지정대리청구서비스특약 약관" in titles
    main = [a for a in doc.articles if a.part == 0]
    assert len(main) >= 55  # 주계약 제1조~제55조 (예전에는 목차 줄만 잡혀서 본문이 0개)
    assert main[0].title == "보장종목" and "질병급여형" in main[0].full_text()
    # 본문이 별표 하나에 몰리지 않음
    assert all(len(x.text) < 100_000 for x in doc.appendices if x.label.startswith("별표"))
    assert not any(a.part is None for a in doc.articles)


def test_real_silson_2605_validation(silson_2605):
    found = codes(validate_structure(silson_2605))
    # 남은 중복은 주계약·특약 안의 《질병급여형》《상해급여형》 제3조·제4조 (약관 원문 구성)
    assert found["ARTICLE_DUPLICATE"] <= 6
    assert found["ARTICLE_ORDER"] <= 5
    assert found["EMPTY_ARTICLE"] == 0


def test_real_small_rider_unchanged():
    doc = _real("중증간병연금전환특약")
    assert len(doc.articles) == 20
    assert sum(len(a.references) for a in doc.articles) == 47
