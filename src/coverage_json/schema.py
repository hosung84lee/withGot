"""보장 JSON 스키마 읽기·검증."""

import json
from functools import cache
from pathlib import Path

import jsonschema

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schema" / "json" / "coverage.json"


@cache
def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _validator() -> jsonschema.Draft202012Validator:
    return jsonschema.Draft202012Validator(load_schema(), format_checker=jsonschema.FormatChecker())


def validate_items(items: list[dict]) -> list[str]:
    """보장 JSON 목록을 검사해 오류 메시지 목록을 돌려줌 (없으면 빈 목록)."""
    v = _validator()
    errors = []
    for i, item in enumerate(items):
        for e in v.iter_errors(item):
            where = "/".join(str(p) for p in e.absolute_path) or "(항목)"
            errors.append(f"[{i}] {item.get('coverage_id', '?')} {where}: {e.message[:200]}")
    return errors
