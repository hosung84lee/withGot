"""사고보장 JSON ↔ 테이블(SQLite) 변환 명령.

    # 저장: 사고보장 JSON(Product, 또는 coverage_extract --out 결과) → DB
    uv run python -m coverage_store save tests/fixtures/silson_2605_disease_covered.json \
        --db coverage.db --id silson-2605

    # 조회: DB 의 상품 목록 / 테이블별 행 수
    uv run python -m coverage_store show --db coverage.db

    # 되돌리기: DB → 사고보장 JSON
    uv run python -m coverage_store load --db coverage.db --id silson-2605 --out out.json
"""

import argparse
import json
import sys
from pathlib import Path

from coverage_store.store import PRODUCT_TABLES, connect, list_products, load_product, save_product
from schema.coverage import Product


def _read_product(path: Path) -> Product:
    data = json.loads(path.read_text(encoding="utf-8"))
    if "product" in data and "coverages" not in data:  # coverage_extract --out 형식
        data = data["product"]
    return Product.model_validate(data)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m coverage_store",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("save", help="사고보장 JSON 을 DB 에 저장")
    s.add_argument("json", type=Path)
    s.add_argument("--db", required=True)
    s.add_argument("--id", required=True, help="상품 id (같은 id 는 덮어씀)")
    sh = sub.add_parser("show", help="상품 목록과 테이블별 행 수")
    sh.add_argument("--db", required=True)
    ld = sub.add_parser("load", help="DB 의 상품을 사고보장 JSON 으로")
    ld.add_argument("--db", required=True)
    ld.add_argument("--id", required=True)
    ld.add_argument("--out", type=Path, help="없으면 화면에 출력")
    args = ap.parse_args(argv)

    conn = connect(args.db)
    if args.cmd == "save":
        product = _read_product(args.json)
        save_product(conn, product, args.id)
        n = len(product.rules()) + len(product.exclusions())
        print(f"저장: {args.id} ({product.name}) · 규칙·보상 제외 {n}건 → {args.db}")
    elif args.cmd == "show":
        for pid, name in list_products(conn):
            counts = {
                t: conn.execute(
                    f"SELECT COUNT(*) FROM {t} WHERE product_id = ?", (pid,)
                ).fetchone()[0]
                for t in reversed(PRODUCT_TABLES)
            }
            print(f"[{pid}] {name}")
            print("  " + " · ".join(f"{t} {n}" for t, n in counts.items()))
    else:
        text = load_product(conn, args.id).model_dump_json(indent=2, exclude_none=True)
        if args.out:
            args.out.write_text(text, encoding="utf-8")
            print(f"저장: {args.out}")
        else:
            sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
