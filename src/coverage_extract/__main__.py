"""사고보장 데이터 추출 명령.

# 추출 묶음만 보기 (API 키 필요 없음)
uv run python -m coverage_extract 약관.pdf --dry-run

# 주계약 《질병급여형》만 OpenAI 로 추출해서 저장
uv run python -m coverage_extract 약관.pdf --provider openai --section 질병급여형 --out out.json

# 이미 있는 사고보장 JSON(정답 파일 등)의 근거만 확인 (API 키 필요 없음)
uv run python -m coverage_extract 약관.pdf --ground tests/fixtures/silson_2605_disease_covered.json

# 추출해서 정답과 비교 (저장해 둔 결과를 다시 비교할 때는 --ground out.json --compare …)
uv run python -m coverage_extract 약관.pdf --provider openai --section 질병급여형 \\
    --out out.json --compare tests/fixtures/silson_2605_disease_covered.json
"""

import argparse
import json
import sys
from pathlib import Path

from coverage_extract.bundles import build_bundles
from coverage_extract.compare import compare_products
from coverage_extract.grounding import GroundingReport, ground_product
from schema.coverage import Product
from terms import parse_terms
from terms.extract import bytes_to_text


def _print_report(report: GroundingReport) -> None:
    p = report.product
    print(f"\n상품: {p.name}")
    for c in p.coverages:
        print(f"  [{c.kind}] {c.name}")
        for r in c.risks:
            for rule in r.rules:
                mark = "✓" if rule.status == "confirmed" else "?"
                print(f"    {mark} {rule.id}  {rule.name}")
        for e in c.exclusions:
            mark = "✓" if e.status == "confirmed" else "?"
            print(f"    {mark} {e.id}  (제외) {e.description[:40]}")
    print(f"\n근거 확인 {report.confirmed}건 · 검토 필요 {report.needs_review}건")
    for i in report.issues:
        print(f"  - [{i.severity}] {i.code} {i.target}: {i.message}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="coverage_extract", description="약관 → 사고보장 데이터")
    ap.add_argument("file", type=Path, help="약관 PDF 또는 TXT")
    ap.add_argument("--dry-run", action="store_true", help="추출 묶음만 출력 (LLM 호출 안 함)")
    ap.add_argument("--ground", type=Path, help="사고보장 JSON 의 근거만 확인 (LLM 호출 안 함)")
    ap.add_argument(
        "--provider", choices=["openai", "anthropic"], help="기본값: .env 의 DEFAULT_PROVIDER"
    )
    ap.add_argument("--model", help="기본값: .env 의 OPENAI_MODEL / ANTHROPIC_MODEL")
    ap.add_argument("--section", action="append", help="이 보장종목만 추출 (여러 번 지정 가능)")
    ap.add_argument("--out", type=Path, help="결과 JSON 저장 경로")
    ap.add_argument("--compare", type=Path, help="결과를 이 정답 JSON 과 비교")
    args = ap.parse_args(argv)

    text = bytes_to_text(args.file.name, args.file.read_bytes())
    doc = parse_terms(text)

    if args.dry_run:
        for b in build_bundles(doc):
            if args.section and not any(s in b.key for s in args.section):
                continue
            body = b.render()
            print(
                f"=== [{b.kind}] {b.key}  ({len(body):,}자, 조: {', '.join(a.label for a in b.articles)})"
            )
        return 0

    if args.ground:
        report = ground_product(_load_product(args.ground), doc)
    else:
        from coverage_extract.extractor import extract_coverage

        report = extract_coverage(
            doc,
            provider=args.provider,
            model=args.model,
            sections=args.section,
            on_progress=lambda i, n, b: print(f"[{i}/{n}] {b.key} 추출 중…", file=sys.stderr),
        )
    _print_report(report)
    if args.out:
        args.out.write_text(
            json.dumps(
                {
                    "product": report.product.model_dump(exclude_none=True),
                    "issues": [i.model_dump() for i in report.issues],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\n저장: {args.out}")
    if args.compare:
        result = compare_products(report.product, _load_product(args.compare))
        print(f"\n정답 비교 ({args.compare.name}): 값까지 일치 {result.score:.0%}")
        for title, rows in [
            ("일치", result.matched),
            ("값이 다름", result.different),
            ("빠짐", result.missing),
            ("정답에 없음", result.extra),
        ]:
            for row in rows:
                print(f"  [{title}] {row}")
    return 0


def _load_product(path: Path) -> Product:
    """사고보장 JSON 읽기. --out 으로 저장한 {"product": …, "issues": …} 모양도 받음."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return Product.model_validate(data.get("product", data))


if __name__ == "__main__":
    raise SystemExit(main())
