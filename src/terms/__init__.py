"""약관 분석 / 구조화 / 검증.

    from terms import parse_terms, validate_structure, run_terms_pipeline

- parser:    원문 텍스트 → 조/항/호/목 구조 (규칙 기반)
- validator: 구조 검증 + AI 분석 결과의 원문 근거 검증 (규칙 기반)
- analyzer:  조별 분류·요약·불공정 조항 검토 (LLM)
- pipeline:  위 단계를 묶어 실행하고 trace 로 기록
"""

from terms.parser import parse_terms
from terms.validator import validate_analysis, validate_structure

__all__ = ["parse_terms", "run_terms_pipeline", "validate_analysis", "validate_structure"]


def __getattr__(name: str):
    # pipeline 은 agent 를 import 하고, agent 는 skills 를 import 합니다.
    # skills 가 terms 를 쓰므로 순환 import 를 피하려고 필요할 때 불러옵니다.
    if name == "run_terms_pipeline":
        from terms.pipeline import run_terms_pipeline

        return run_terms_pipeline
    raise AttributeError(name)
