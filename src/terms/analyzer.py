"""구조화된 약관 → LLM 분석 (조별 분류·요약·불공정 조항 검토 + 전체 개요).

- 원문 대신 구조화 결과를 '조 표기' 와 함께 보내서, 모델이 조를 정확히 가리키게 합니다.
- 긴 약관은 조 단위로 나눠 여러 번 분석한 뒤, 조별 요약으로 전체 개요를 한 번 더 만듭니다.
- 응답은 JSON 으로 받아 Pydantic 으로 검사하고, 형식이 틀리면 에러를 알려주고 다시 받습니다.
- 내용이 원문에 근거하는지는 validator.validate_analysis 가 따로 확인합니다.
"""

import json
import re
from collections.abc import Callable
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from agent import Agent
from agent.llm import OpenAIClient
from backend.tracing import span
from schema.agent import AgentMessage
from schema.terms import (
    CLAUSE_CATEGORIES,
    UNFAIR_TYPES,
    Article,
    ClauseAnalysis,
    TermsAnalysis,
    TermsDocument,
    TermsOverview,
)

M = TypeVar("M", bound=BaseModel)

DEFAULT_CHUNK_CHARS = 30_000  # 한 번에 보낼 조문 분량 (문자 수)
JSON_RETRIES = 2

SYSTEM = f"""너는 한국 약관을 심사하는 법률 전문가다.
「약관의 규제에 관한 법률」(약관규제법) 기준으로 약관을 조 단위로 검토한다.

규칙
- 반드시 요청한 JSON 하나만 출력한다. 설명 문장이나 코드블록 표시(```)를 붙이지 않는다.
- 조 표기(article)는 입력의 '### ' 뒤에 적힌 표기를 그대로 쓴다. 예: 제12조, 제3조의2, 부칙 제1조
- quote 는 해당 조 본문에서 글자 그대로 복사한다. 바꿔 쓰거나 요약하지 않는다.
- 고객에게 불리하다고 볼 근거가 없으면 risk 를 none 으로 두고 issues 는 빈 배열로 둔다.
- 추측하지 말고 원문에 있는 내용만 근거로 삼는다.

category 는 다음 중 하나: {", ".join(CLAUSE_CATEGORIES)}
issues[].type 은 다음 중 하나:
{chr(10).join(f"- {k}: {v}" for k, v in UNFAIR_TYPES.items())}
risk: none(문제 없음) | low(주의) | medium(고객에게 불리할 수 있음) | high(무효 가능성이 큼)
"""

CLAUSE_PROMPT = """다음 약관 조문을 조마다 하나씩 분석해서 아래 형식의 JSON 으로 답해.
입력에 있는 조는 빠짐없이 모두 포함해. ('삭제'된 조는 제외)

{{"clauses": [{{"article": "제1조", "category": "...", "summary": "한두 문장 요약",
  "risk": "none|low|medium|high",
  "issues": [{{"type": "...", "description": "왜 문제인지", "quote": "원문 그대로",
              "legal_basis": "예: 약관규제법 제7조"}}]}}]}}

약관 제목: {title}

{articles}"""

OVERVIEW_PROMPT = """다음은 약관 '{title}'의 조별 분석 요약이다. 이를 바탕으로 약관 전체 개요를
아래 형식의 JSON 으로 답해.

{{"document_type": "예: 보험 약관, 서비스 이용약관", "parties": ["계약 당사자"],
  "summary": "약관 전체를 3~5문장으로 요약",
  "key_points": ["고객이 꼭 알아야 할 점 (주의할 조항은 조 표기 포함)"]}}

머리말: {preamble}

{clauses}"""


class AnalysisError(RuntimeError):
    pass


class _ClauseBatch(BaseModel):
    clauses: list[ClauseAnalysis]


def article_block(a: Article) -> str:
    head = f"### {a.label}" + (f" ({a.title})" if a.title else "")
    if a.path:
        head += f"  [{' > '.join(a.path)}]"
    return f"{head}\n{a.full_text()}"


def chunk_articles(articles: list[Article], max_chars: int) -> list[list[Article]]:
    chunks: list[list[Article]] = []
    size = 0
    for a in articles:
        n = len(article_block(a))
        if chunks and size + n <= max_chars:
            chunks[-1].append(a)
            size += n
        else:
            chunks.append([a])
            size = n
    return chunks


def extract_json(text: str) -> str:
    """응답에서 JSON 객체 부분만 꺼냄 (코드블록이나 앞뒤 설명이 붙어도)."""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("응답에 JSON 객체가 없습니다.")
    return text[start : end + 1]


def ask_json(agent: Agent, prompt: str, model: type[M], retries: int = JSON_RETRIES) -> M:
    """JSON 응답을 받아 model 로 검사. 틀리면 에러 내용을 알려주고 다시 받음."""
    history = [AgentMessage(role="user", content=prompt)]
    last_error = ""
    for _ in range(retries + 1):
        result = agent.run(history)
        if result.stop_reason != "end":
            raise AnalysisError(
                f"분석 응답이 정상 종료되지 않았습니다 (stop_reason={result.stop_reason}). "
                + (
                    "조문이 길면 chunk_chars 를 줄이거나 AGENT_MAX_TOKENS 를 늘리세요."
                    if result.stop_reason == "max_tokens"
                    else ""
                )
            )
        try:
            return model.model_validate_json(extract_json(result.output))
        except (ValidationError, ValueError) as e:
            last_error = str(e)
            history = result.messages + [
                AgentMessage(
                    role="user",
                    content=f"JSON 형식이 잘못되었습니다:\n{last_error[:2000]}\n"
                    "형식에 맞는 JSON 하나만 다시 출력해.",
                )
            ]
    raise AnalysisError(f"{retries + 1}번 시도했지만 올바른 JSON 을 받지 못했습니다: {last_error}")


def analyze_terms(
    doc: TermsDocument,
    llm: OpenAIClient | None = None,
    model: str | None = None,
    chunk_chars: int = DEFAULT_CHUNK_CHARS,
    on_progress: Callable[[int, int], None] | None = None,
) -> TermsAnalysis:
    targets = [a for a in doc.articles if not a.deleted]
    if not targets:
        raise AnalysisError("분석할 조가 없습니다.")
    agent = Agent(model, llm=llm, system=SYSTEM, tools=[], max_turns=1, name="terms-analyzer")
    title = doc.title or "(제목 없음)"

    chunks = chunk_articles(targets, chunk_chars)
    clauses: list[ClauseAnalysis] = []
    for i, chunk in enumerate(chunks, start=1):
        if on_progress:
            on_progress(i, len(chunks) + 1)
        with span(
            "step", f"조별 분석 {i}/{len(chunks)}", input={"articles": [a.label for a in chunk]}
        ) as s:
            batch = ask_json(
                agent,
                CLAUSE_PROMPT.format(
                    title=title, articles="\n\n".join(article_block(a) for a in chunk)
                ),
                _ClauseBatch,
            )
            s.set(output={"clauses": len(batch.clauses)})
        clauses += batch.clauses

    if on_progress:
        on_progress(len(chunks) + 1, len(chunks) + 1)
    with span("step", "전체 개요") as s:
        summary_lines = [
            json.dumps(
                {
                    "article": c.article,
                    "category": c.category,
                    "summary": c.summary,
                    "risk": c.risk,
                    "issues": [i.description for i in c.issues],
                },
                ensure_ascii=False,
            )
            for c in clauses
        ]
        overview = ask_json(
            agent,
            OVERVIEW_PROMPT.format(
                title=title,
                preamble=doc.preamble[:2000] or "(없음)",
                clauses="\n".join(summary_lines),
            ),
            TermsOverview,
        )
        s.set(output=overview.model_dump())

    return TermsAnalysis(overview=overview, clauses=clauses, model=agent.llm.model)
