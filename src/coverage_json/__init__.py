"""보장 JSON 스키마(src/schema/json/coverage.json) 도우미.

- schema: 스키마 읽기·검증
- kcd: KCD 범위 → 정규식 (kcd_code_patterns)
- convert: 사고보장 데이터(schema.coverage.Product) → 보장 JSON 목록
- compare: 두 약관의 보장 JSON 비교
"""

from .compare import compare_items
from .convert import product_to_items
from .kcd import range_to_patterns
from .schema import load_schema, validate_items

__all__ = [
    "compare_items",
    "load_schema",
    "product_to_items",
    "range_to_patterns",
    "validate_items",
]
