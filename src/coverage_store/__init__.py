"""사고보장 데이터(schema.coverage.Product)를 관계형 테이블(SQLite)에 저장·조회.

    from coverage_store import connect, save_product, load_product

    conn = connect("coverage.db")
    save_product(conn, product, "silson-2605")
    product = load_product(conn, "silson-2605")

테이블 설계: docs/coverage_tables.md, 정의: coverage_store/schema.sql
"""

from coverage_store.store import (
    CONDITION_ITEMS,
    connect,
    delete_product,
    list_products,
    load_product,
    save_product,
)

__all__ = [
    "CONDITION_ITEMS",
    "connect",
    "delete_product",
    "list_products",
    "load_product",
    "save_product",
]
