"""약관 → 보장 JSON(coverage.json 스키마) 직접 추출 (OpenAI).

보장 묶음(약관 × 보장종목, coverage_extract.bundles)마다 조문 + 그 약관의 '보험금 지급기준표' 별표를 넣고,
스키마를 보여 준 뒤 보장 JSON 배열을 받습니다. jsonschema 로 검사해 틀리면 오류를 알려 다시 받고,
그래도 틀리면 맞는 항목만 남깁니다.
"""

import contextvars
import json
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

from agent import Agent
from agent.llm import OpenAIClient
from coverage_extract.bundles import Bundle, build_bundles
from schema.agent import AgentMessage
from schema.terms import TermsDocument
from terms.analyzer import extract_json

from .schema import load_schema, validate_items

RETRIES = 2
WORKERS = 6

SYSTEM = """너는 한국 보험 약관을 읽고 보장 하나하나를 정해진 JSON 스키마로 옮기는 전문가다.

규칙
- 반드시 JSON 객체 하나만 출력한다: {"items": [보장 JSON, ...]}. 설명이나 코드블록 표시를 붙이지 않는다.
- 입력에 있는 내용만 쓴다. 추측하지 말고 모르면 null 또는 '판단불가'.
- 비율은 0~1 소수(40% → 0.4, 120% → 1.2), 금액은 원 단위 숫자.
- 보장 = 보험금 지급사유 하나. 지급 조건(대상 질병·감액·면책)이 같은 여러 보험금은 benefits 에 함께 둔다.
- 실손은 보장종목 하나를 보장 하나로 하고(claim_reason '의료비'), 입원/통원·급여/비급여·의료기관별 규칙을 indemnity.rules 에 나눈다.
- 코드로 판정할 수 있는 조건(날짜·횟수·이력·의료기관 종별)은 pgm_review_items, 서류를 읽고 판단해야 하는 조건(병기·조직형·치료 목적)은 ai_review_items 에 쓴다.
- source.quote 는 원문에서 글자 그대로 복사한 짧은 문구.
- coverage_id 는 스키마 설명의 규칙을 따른다 (회사-상품-약관-보장종목-보장, 대문자·숫자·하이픈)."""

PROMPT = """아래 JSON 스키마(보장 하나의 모양)에 맞춰, 약관 조문에서 보장을 모두 뽑아 {{"items": [...]}} 로 답해.

스키마
{schema}

약관 조문
{body}"""


def _compact_schema() -> str:
    """프롬프트용 스키마 (설명은 남기고 $schema·$id 는 뺌)."""
    s = {k: v for k, v in load_schema().items() if not k.startswith("$") or k == "$defs"}
    return json.dumps(s, ensure_ascii=False, separators=(",", ":"))


def appendix_for(doc: TermsDocument, bundle: Bundle) -> str:
    """묶음의 약관 범위 안에 있는 '보험금 지급기준표' 별표 원문 (정액형 지급 금액·감액이 여기 있음)."""
    if bundle.part is None or not doc.parts:
        lo, hi = 0, 10**9
    else:
        lo = doc.parts[bundle.part].line
        hi = doc.parts[bundle.part + 1].line if bundle.part + 1 < len(doc.parts) else 10**9
    tables = [x for x in doc.appendices if lo <= x.line < hi and "지급기준표" in x.label]
    return "\n\n".join(f"### {x.label}\n{x.text}" for x in tables)


def render(doc: TermsDocument, bundle: Bundle) -> str:
    body = bundle.render()
    table = appendix_for(doc, bundle)
    return body + (f"\n\n{table}" if table else "")


def ask_items(agent: Agent, prompt: str) -> tuple[list[dict], list[str]]:
    """보장 JSON 배열을 받아 검사. (맞는 항목, 남은 오류)."""
    history = [AgentMessage(role="user", content=prompt)]
    items: list[dict] = []
    errors: list[str] = ["응답 없음"]
    for _ in range(RETRIES + 1):
        result = agent.run(history)
        if result.stop_reason != "end":
            raise RuntimeError(
                f"응답이 정상 종료되지 않았습니다 (stop_reason={result.stop_reason})"
            )
        try:
            data = json.loads(extract_json(result.output))
            items = data.get("items") if isinstance(data, dict) else data
            if not isinstance(items, list):
                raise ValueError("items 배열이 없습니다.")  # noqa: TRY004 — 아래에서 함께 처리
            errors = validate_items(items)
        except ValueError as e:
            items, errors = [], [str(e)]
        if not errors:
            return items, []
        history = result.messages + [
            AgentMessage(
                role="user",
                content="스키마에 맞지 않습니다:\n"
                + "\n".join(errors[:20])
                + "\n고쳐서 JSON 하나만 다시 출력해.",
            )
        ]
    bad = {int(m.group(1)) for e in errors if (m := re.match(r"\[(\d+)\]", e))}
    return [x for i, x in enumerate(items) if i not in bad], errors


def extract_items(
    doc: TermsDocument,
    keys: list[str] | None = None,
    llm: OpenAIClient | None = None,
    model: str | None = None,
    on_progress: Callable[[int, int, Bundle], None] | None = None,
    workers: int | None = None,
) -> dict[str, dict]:
    """묶음별 결과 {묶음 key: {"items": [...], "errors": [...]}} (실패한 묶음은 items 빈 목록 + errors)."""
    bundles = [b for b in build_bundles(doc) if keys is None or b.key in keys]
    agent = Agent(model, llm=llm, system=SYSTEM, tools=[], max_turns=1, name="coverage-json")
    schema = _compact_schema()
    workers = workers or (1 if llm is not None else WORKERS)
    out: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                contextvars.copy_context().run,
                ask_items,
                agent,
                PROMPT.format(schema=schema, body=render(doc, b)),
            ): b
            for b in bundles
        }
        for n, f in enumerate(as_completed(futures), start=1):
            b = futures[f]
            try:
                items, errors = f.result()
                out[b.key] = {"items": items, "errors": errors}
            except Exception as e:  # noqa: BLE001 — 묶음 하나가 실패해도 나머지는 계속
                out[b.key] = {"items": [], "errors": [f"{type(e).__name__}: {e}"]}
            if on_progress:
                on_progress(n, len(bundles), b)
    return out
