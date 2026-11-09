"""약관 구조화 결과 → 사고보장 데이터 (schema.coverage.Product).

bundles: 보장 조를 보장종목 단위로 묶음 (LLM 없음)
extractor: 묶음마다 LLM 으로 지급 규칙·보상 제외를 추출
grounding: 추출 결과의 인용문·숫자가 약관 원문에 있는지 확인 (LLM 없음)
"""

from coverage_extract.bundles import Bundle, build_bundles

__all__ = ["Bundle", "build_bundles"]
