"""추출 묶음 → LLM → 사고보장 데이터 (schema.coverage.Product).

묶음(약관 하나 × 보장종목 하나)마다 LLM 에 지급 규칙·보상 제외를 JSON 으로 받고,
id 는 코드에서 다시 매긴 뒤(묶음끼리 겹치지 않게) grounding 으로 근거를 확인합니다.
LLM 은 OpenAI (agent.Agent). 모델 기본값은 .env 의 OPENAI_MODEL.
"""

import contextvars
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

from pydantic import BaseModel, Field

from agent import Agent
from agent.llm import OpenAIClient
from backend.tracing import span
from coverage_extract.bundles import Bundle, build_bundles
from coverage_extract.grounding import GroundingIssue, GroundingReport, ground_product
from schema.coverage import Coverage, CoverageCode, Exclusion, Product, Risk
from schema.terms import TermsDocument
from terms.analyzer import ask_json

SYSTEM = """너는 한국 보험 약관에서 보상 규칙을 뽑아 표준 JSON 으로 옮기는 전문가다.

규칙
- 반드시 요청한 JSON 하나만 출력한다. 설명 문장이나 코드블록 표시(```)를 붙이지 않는다.
- 입력에 있는 내용만 쓴다. 추측하거나 다른 상품 지식으로 채우지 않는다.
- 금액은 원 단위 정수로 쓴다. 예: 20만원 → 200000, 5천만원 → 50000000.
- 비율은 {"numerator": 80, "denominator": 100} 처럼 쓴다.
- 모든 규칙과 보상 제외에 source 를 단다.
  source.part 는 입력의 '약관:' 값을, source.section 은 '보장종목:' 값을 그대로 쓴다.
  source.article 은 '### ' 뒤의 조 표기(예: 제3조)를, paragraph 는 항 번호(①=1)를 쓴다.
  source.quote 는 그 조 본문에서 글자 그대로 복사한 짧은 문구다 (바꿔 쓰거나 요약하지 않는다).
- 한도처럼 다른 조(예: 제5조)에 근거가 있으면 extra_sources 에 그 조를 추가한다.
- status 는 모두 "needs_review" 로 둔다 (근거 확인은 따로 한다).
"""

PROMPT = """다음 약관 조문에서 보상 규칙과 보상하지 않는 사항을 뽑아 아래 형식의 JSON 으로 답해.

형식
{{"risks": [
  {{"id": "임시id", "claim_reason": "hospitalization|outpatient|diagnosis|surgery|death|disability|other",
    "section": "보장종목 (없으면 null)",
    "rules": [
      {{"id": "임시id", "name": "규칙 이름 (예: 급여 입원, 급여 통원 - 의원)",
        "conditions": {{
          "facility": "의료기관 조건 (없으면 null)",
          "limit": {{"amounts": [{{"amount": 200000, "per": "visit|day|stay|year|daily_average|event",
                                  "selectable": true}}]}},
          "extension": {{"days": 180, "max_visits": 90}}
        }},
        "special_conditions": [{{"type": "예: no_health_insurance", "description": "..."}}],
        "benefit": {{"type": "actual_cost|rate|fixed", "base": "medical_cost|sum_insured",
                    "cost_type": "covered|non_covered|room_difference",
                    "ratio": {{"numerator": 80, "denominator": 100}},
                    "deductible": {{"amounts": [10000], "ratios": [{{"numerator": 20, "denominator": 100}}],
                                   "copay_rate": true, "pick": "max"}},
                    "copay_cap_annual": 2000000}},
        "source": {{"part": "...", "section": "...", "article": "제3조", "paragraph": 1, "quote": "원문 그대로"}},
        "extra_sources": [],
        "status": "needs_review"}}
    ]}}
 ],
 "exclusions": [
   {{"id": "임시id", "kind": "kcd|cost_item|cause", "description": "무엇을 보상하지 않는지",
     "coverage_code": "kind=kcd 면 coverage_codes 의 code", "exception": "다만 … 보상 (없으면 빈 문자열)",
     "section": "...", "source": {{...}}, "status": "needs_review"}}
 ],
 "coverage_codes": [
   {{"code": "예: EXCL_F04_F99", "name": "정신 및 행동장애",
     "kcd": [{{"start": "F04", "end": "F99"}}], "source": {{...}}}}
 ]}}

지침
- 쓰지 않는 항목은 빼거나 null 로 둔다.
- 입원·통원처럼 보상 방식이 다르면 risk 를 나눈다. 의료기관별로 공제금액이 다르면 rule 을 나눈다.
- 건강보험을 적용받지 못하는 경우처럼 조건이 다른 보상은 별도 rule 로, special_conditions 에 조건을 쓴다.

{body}"""


class ExtractionError(RuntimeError):
    pass


class SectionExtraction(BaseModel):
    """묶음 하나에서 받은 결과."""

    risks: list[Risk] = Field(default_factory=list)
    exclusions: list[Exclusion] = Field(default_factory=list)
    coverage_codes: list[CoverageCode] = Field(default_factory=list)


def _slug(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "", text)[:30] or "x"


def _reassign_ids(result: SectionExtraction, prefix: str) -> SectionExtraction:
    """LLM 이 붙인 임시 id 를 묶음 기준의 안정적인 id 로 바꿈 (개정 비교에 씀)."""
    result = result.model_copy(deep=True)
    rule_map: dict[str, str] = {}
    for i, risk in enumerate(result.risks, start=1):
        risk.id = f"{prefix}/{risk.claim_reason}{i}"
        for j, rule in enumerate(risk.rules, start=1):
            new = f"{risk.id}/{j}"
            rule_map[rule.id] = new
            rule.id = new
            rule.status = "needs_review"
    for risk in result.risks:
        for rule in risk.rules:
            for s in rule.special_conditions:
                if s.related_rule_id:
                    s.related_rule_id = rule_map.get(s.related_rule_id, s.related_rule_id)
    code_map = {c.code: f"{prefix}/{_slug(c.code)}" for c in result.coverage_codes}
    for c in result.coverage_codes:
        c.code = code_map[c.code]
    for risk in result.risks:
        if risk.coverage_code:
            risk.coverage_code = code_map.get(risk.coverage_code, risk.coverage_code)
    for k, ex in enumerate(result.exclusions, start=1):
        ex.id = f"{prefix}/exclusion{k}"
        ex.status = "needs_review"
        if ex.coverage_code:
            ex.coverage_code = code_map.get(ex.coverage_code, ex.coverage_code)
    return result


def assemble(doc: TermsDocument, results: list[tuple[Bundle, SectionExtraction]]) -> Product:
    """묶음별 결과를 약관(보장) 단위로 합쳐 Product 하나로."""
    coverages: dict[str, Coverage] = {}
    codes: list[CoverageCode] = []
    for i, (bundle, result) in enumerate(results):
        cov_id = f"p{bundle.part if bundle.part is not None else 0}"
        prefix = f"{cov_id}/{_slug(bundle.section or 'all')}"
        fixed = _reassign_ids(result, prefix)
        cov = coverages.setdefault(
            cov_id,
            Coverage(id=cov_id, name=bundle.part_title, kind=bundle.kind),  # type: ignore[arg-type]
        )
        cov.risks += fixed.risks
        cov.exclusions += fixed.exclusions
        codes += fixed.coverage_codes
    name = doc.parts[0].title if doc.parts else (doc.title or "약관")
    return Product(name=name, coverages=list(coverages.values()), coverage_codes=codes)


DEFAULT_WORKERS = 6  # 묶음을 동시에 보내는 수


def extract_sections(
    bundles: list[Bundle],
    llm: OpenAIClient | None = None,
    model: str | None = None,
    workers: int | None = None,
    on_progress: Callable[[int, int, Bundle], None] | None = None,
) -> tuple[list[tuple[Bundle, SectionExtraction]], dict[str, str]]:
    """묶음들을 LLM 으로 추출 (동시에 workers 개). (성공 결과, {실패 묶음 key: 오류}).

    llm 을 직접 주면(테스트용 가짜 등) 기본 workers=1 (응답 순서 보장).
    on_progress(끝난 수, 전체, 묶음) 은 호출한 스레드에서 불림.
    """
    if workers is None:
        workers = 1 if llm is not None else DEFAULT_WORKERS
    agent = Agent(model, llm=llm, system=SYSTEM, tools=[], max_turns=1, name="coverage-extractor")

    def run(i: int, bundle: Bundle) -> SectionExtraction:
        with span("step", f"사고보장 추출 {i}/{len(bundles)}", input={"bundle": bundle.key}) as s:
            result = ask_json(agent, PROMPT.format(body=bundle.render()), SectionExtraction)
            s.set(output={"risks": len(result.risks), "exclusions": len(result.exclusions)})
        return result

    done: dict[int, SectionExtraction] = {}
    errors: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {
            pool.submit(contextvars.copy_context().run, run, i, b): i
            for i, b in enumerate(bundles, start=1)
        }
        for n, f in enumerate(as_completed(futures), start=1):
            i = futures[f]
            try:
                done[i] = f.result()
            except Exception as e:  # noqa: BLE001 — 묶음 하나가 실패해도 나머지는 계속
                errors[bundles[i - 1].key] = f"{type(e).__name__}: {e}"
            if on_progress:
                on_progress(n, len(bundles), bundles[i - 1])
    return [(bundles[i - 1], done[i]) for i in sorted(done)], errors


def extract_coverage(
    doc: TermsDocument,
    llm: OpenAIClient | None = None,
    model: str | None = None,
    sections: list[str] | None = None,
    on_progress: Callable[[int, int, Bundle], None] | None = None,
    workers: int | None = None,
) -> GroundingReport:
    """구조화된 약관에서 사고보장 데이터를 뽑고 근거를 확인한 결과를 돌려줌.

    sections 를 주면 그 보장종목(또는 약관 제목에 그 글자가 든 묶음)만 추출합니다.
    예: ["질병급여형"] → 주계약 《질병급여형》 묶음 하나만 (API 비용·시간 절약).
    묶음은 동시에 추출하고, 실패한 묶음은 EXTRACTION_FAILED 오류로 report.issues 에 남깁니다.
    """
    bundles = build_bundles(doc)
    if sections:
        bundles = [b for b in bundles if any(s in b.key for s in sections)]
    if not bundles:
        raise ExtractionError(
            "추출할 보장 묶음이 없습니다. 보장 조(보상내용 등)를 찾지 못했습니다."
        )
    results, errors = extract_sections(bundles, llm, model, workers, on_progress)
    if not results:
        raise ExtractionError(f"모든 묶음 추출에 실패했습니다: {next(iter(errors.values()))}")
    report = ground_product(assemble(doc, results), doc)
    report.issues += failed_issues(errors)
    return report


def failed_issues(errors: dict[str, str]) -> list[GroundingIssue]:
    return [
        GroundingIssue(severity="error", code="EXTRACTION_FAILED", target=key, message=msg[:500])
        for key, msg in errors.items()
    ]
