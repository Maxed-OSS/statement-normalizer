"""Command-line entrypoint: normalize statement files to JSON.

Examples
--------
    statement-normalizer statement.csv
    statement-normalizer --format ofx export.qfx --pretty
    statement-normalizer jan.csv feb.csv --merge -o all.json
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Optional, Sequence

from . import __version__
from .normalize import FORMATS, normalize_file, normalize_many
from .util import ParseError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="statement-normalizer",
        description=(
            "Normalize bank & credit-card statements (CSV, OFX/QFX, text) into "
            "clean transaction JSON. Deterministic, rule-based, no ML."
        ),
    )
    parser.add_argument("files", nargs="+", help="statement file(s) to normalize")
    parser.add_argument(
        "--format",
        choices=FORMATS,
        default=None,
        help="force input format (default: auto-detect by extension/content)",
    )
    parser.add_argument(
        "--currency",
        default="USD",
        help="default ISO currency code when the source omits one (default: USD)",
    )
    parser.add_argument(
        "--merge",
        action="store_true",
        help="merge all input files into one de-duplicated transaction list",
    )
    parser.add_argument(
        "--no-dedup",
        action="store_true",
        help="disable de-duplication",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="write JSON to this file instead of stdout",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="pretty-print JSON output",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"statement-normalizer {__version__}",
    )
    return parser


def _emit(payload, output: Optional[str], pretty: bool) -> None:
    text = json.dumps(payload, indent=2 if pretty else None, sort_keys=False)
    if output:
        with open(output, "w", encoding="utf-8") as fh:
            fh.write(text)
    else:
        sys.stdout.write(text + "\n")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.merge and len(args.files) > 1:
            txns = normalize_many(args.files, default_currency=args.currency)
            payload = {
                "merged": True,
                "source_files": list(args.files),
                "transaction_count": len(txns),
                "transactions": [t.to_dict() for t in txns],
            }
            _emit(payload, args.output, args.pretty)
            return 0

        results = []
        for path in args.files:
            statement = normalize_file(
                path,
                fmt=args.format,
                default_currency=args.currency,
                dedup=not args.no_dedup,
            )
            entry = statement.to_dict()
            entry["source_file"] = path
            results.append(entry)

        payload = results[0] if len(results) == 1 else {"statements": results}
        _emit(payload, args.output, args.pretty)
        return 0

    except (ParseError, FileNotFoundError) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
