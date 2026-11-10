"""약관별 보장 JSON 만들기 (AI 추출 캐시 → 없으면 기존 사고보장 데이터 변환).

캐시: src/data/cache/schema/<원본 파일 해시>/<묶음>.json  ({"bundle", "items", "errors"})
"""

import json
from collections.abc import Callable
from pathlib import Path

from coverage_extract.bundles import Bundle, build_bundles
from coverage_map import policy
from schema.terms import TermsDocument

from .convert import product_to_items


def _dir(key: str) -> Path:
    return policy.CACHE_DIR / "schema" / key


def cached(key: str) -> dict[str, dict]:
    folder = _dir(key)
    out = {}
    for f in sorted(folder.glob("*.json")) if folder.exists() else []:
        data = json.loads(f.read_text(encoding="utf-8"))
        out[data["bundle"]] = data
    return out


def extract_missing(
    key: str,
    doc: TermsDocument,
    model: str | None = None,
    on_progress: Callable[[int, int, Bundle], None] | None = None,
) -> dict[str, list[str]]:
    """캐시에 없는(또는 항목이 하나도 없던) 묶음만 AI 로 스키마 추출. {실패·부분 실패 묶음: 오류}."""
    from .extract import extract_items

    have = {k for k, v in cached(key).items() if v.get("items")}
    todo = [b.key for b in build_bundles(doc) if b.key not in have]
    if not todo:
        return {}
    result = extract_items(doc, todo, model=model, on_progress=on_progress)
    folder = _dir(key)
    folder.mkdir(parents=True, exist_ok=True)
    for bundle_key, data in result.items():
        if data["items"]:  # 항목이 하나도 없으면 캐시하지 않음 (다음에 다시 시도)
            payload = {"bundle": bundle_key, **data}
            (folder / f"{policy._slug(bundle_key)}.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
            )
    return {k: v["errors"] for k, v in result.items() if v["errors"]}


def items_for(doc: TermsDocument, key: str) -> tuple[list[dict], str]:
    """(보장 JSON 목록, 출처 설명). AI 스키마 추출 캐시가 있으면 그것, 없으면 사고보장 데이터 변환."""
    ai = cached(key)
    if ai:
        items = [x for v in ai.values() for x in v["items"]]
        return items, f"AI 스키마 추출 {len(ai)}묶음"
    golden = policy.golden_for(doc)
    product = policy.build_product(doc, key, golden)
    if not product:
        return [], "데이터 없음"
    src = []
    if golden:
        src.append("정답 초안" if policy.is_draft(golden) else "정답 데이터")
    n = len(policy.cached_sections(key))
    if n:
        src.append(f"AI 사고보장 {n}묶음")
    return product_to_items(product), " + ".join(src) + " → 스키마 변환"
