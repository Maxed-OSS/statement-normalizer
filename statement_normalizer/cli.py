"""Command-line entrypoint: normalize statement files to JSON or CSV.

Examples
--------
    statement-normalizer statement.csv
    statement-normalizer --format ofx export.qfx --pretty
    statement-normalizer jan.csv feb.csv --merge -o all.json
    statement-normalizer statement.mt940 --stats
    statement-normalizer export.camt053.xml --csv -o txns.csv
    cat statement.csv | statement-normalizer --format csv -    # stdin
"""

from __future__ import annotations

import argparse
import csv as _csv
import io
import json
import sys
from decimal import Decimal
from typing import Optional, Sequence

from . import __version__
from .normalize import FORMATS, normalize_bytes, normalize_many
from .schema import Transaction
from .util import ParseError

# Sentinel filename meaning "read from stdin".
_STDIN = "-"

# Column order for --csv output.
_CSV_COLUMNS = [
    "date",
    "amount",
    "description",
    "txn_type",
    "currency",
    "balance",
    "fitid",
    "account_id",
    "source_format",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="statement-normalizer",
        description=(
            "Normalize bank & credit-card statements (CSV, OFX/QFX, MT940, "
            "CAMT.053, CAMT.052, QIF, text) into clean transaction JSON or CSV. "
            "Deterministic, rule-based, no ML."
        ),
    )
    parser.add_argument(
        "files",
        nargs="+",
        help="statement file(s) to normalize; use '-' to read from stdin",
    )
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
        "--invert-amounts",
        dest="invert_amounts",
        action="store_true",
        help=(
            "flip the sign of CSV single-Amount-column values; use for issuers "
            "that report charges as positive / payments as negative"
        ),
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="write output to this file instead of stdout",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="pretty-print JSON output",
    )
    parser.add_argument(
        "--csv",
        dest="as_csv",
        action="store_true",
        help="emit a flat CSV of transactions instead of JSON",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="print a summary (counts, totals, date range) to stderr",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"statement-normalizer {__version__}",
    )
    return parser


def _read_input(path: str) -> bytes:
    if path == _STDIN:
        return sys.stdin.buffer.read()
    with open(path, "rb") as fh:
        return fh.read()


def _normalize_one(path: str, args) -> "object":
    data = _read_input(path)
    filename = None if path == _STDIN else path
    return normalize_bytes(
        data,
        fmt=args.format,
        filename=filename,
        default_currency=args.currency,
        dedup=not args.no_dedup,
        invert_amount=args.invert_amounts,
    )


def _emit_text(text: str, output: Optional[str]) -> None:
    if output:
        with open(output, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
    else:
        sys.stdout.write(text if text.endswith("\n") else text + "\n")


def _emit_json(payload, output: Optional[str], pretty: bool) -> None:
    text = json.dumps(payload, indent=2 if pretty else None, sort_keys=False)
    _emit_text(text, output)


def _emit_csv(txns: Sequence[Transaction], output: Optional[str]) -> None:
    buf = io.StringIO()
    writer = _csv.DictWriter(buf, fieldnames=_CSV_COLUMNS)
    writer.writeheader()
    for txn in txns:
        row = txn.to_dict()
        writer.writerow({col: ("" if row[col] is None else row[col]) for col in _CSV_COLUMNS})
    _emit_text(buf.getvalue(), output)


def _compute_stats(txns: Sequence[Transaction]) -> dict:
    """Deterministic summary over a transaction list."""
    debits = [t for t in txns if t.amount < 0]
    credits = [t for t in txns if t.amount > 0]
    total_in = sum((t.amount for t in credits), Decimal("0"))
    total_out = sum((t.amount for t in debits), Decimal("0"))
    dates = [t.date for t in txns]
    currencies = sorted({t.currency for t in txns})
    return {
        "transactions": len(txns),
        "debits": len(debits),
        "credits": len(credits),
        "total_in": f"{total_in:.2f}",
        "total_out": f"{total_out:.2f}",
        "net": f"{(total_in + total_out):.2f}",
        "date_min": min(dates).isoformat() if dates else None,
        "date_max": max(dates).isoformat() if dates else None,
        "currencies": currencies,
    }


def _print_stats(txns: Sequence[Transaction]) -> None:
    s = _compute_stats(txns)
    lines = [
        "summary:",
        f"  transactions : {s['transactions']}",
        f"  debits       : {s['debits']}  (total out {s['total_out']})",
        f"  credits      : {s['credits']}  (total in  {s['total_in']})",
        f"  net          : {s['net']}",
        f"  date range   : {s['date_min']} .. {s['date_max']}",
        f"  currencies   : {', '.join(s['currencies']) if s['currencies'] else '-'}",
    ]
    sys.stderr.write("\n".join(lines) + "\n")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.merge and len(args.files) > 1:
            datas = [(_read_input(p), (None if p == _STDIN else p)) for p in args.files]
            txns = normalize_many(
                datas,
                fmt=args.format,
                default_currency=args.currency,
                invert_amount=args.invert_amounts,
            )
            if args.stats:
                _print_stats(txns)
            if args.as_csv:
                _emit_csv(txns, args.output)
            else:
                payload = {
                    "merged": True,
                    "source_files": list(args.files),
                    "transaction_count": len(txns),
                    "transactions": [t.to_dict() for t in txns],
                }
                _emit_json(payload, args.output, args.pretty)
            return 0

        statements = [_normalize_one(p, args) for p in args.files]
        all_txns: list[Transaction] = []
        for stmt in statements:
            all_txns.extend(stmt.transactions)

        if args.stats:
            _print_stats(all_txns)

        if args.as_csv:
            _emit_csv(all_txns, args.output)
            return 0

        results = []
        for path, stmt in zip(args.files, statements):
            entry = stmt.to_dict()
            entry["source_file"] = path
            results.append(entry)

        payload = results[0] if len(results) == 1 else {"statements": results}
        _emit_json(payload, args.output, args.pretty)
        return 0

    except (ParseError, FileNotFoundError) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
