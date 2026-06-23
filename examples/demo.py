#!/usr/bin/env python3
"""Runnable tour of statement-normalizer over the synthetic example statements.

Run it from the repo root::

    python examples/demo.py

Everything here uses the committed synthetic files in this directory. No real
account data is involved.
"""

from __future__ import annotations

import os

from statement_normalizer import normalize_file
from statement_normalizer.normalize import normalize_bytes, normalize_many

HERE = os.path.dirname(os.path.abspath(__file__))


def _path(name: str) -> str:
    return os.path.join(HERE, name)


def show(name: str, **kwargs) -> None:
    stmt = normalize_file(_path(name), **kwargs)
    print(f"\n# {name}  ({stmt.source_format}, {stmt.currency})")
    for txn in stmt.transactions:
        print(f"  {txn.date}  {txn.amount:>10}  {txn.txn_type.value:<6}  {txn.description}")


def main() -> None:
    print("=" * 72)
    print("statement-normalizer — example tour")
    print("=" * 72)

    # 1. A spread of real-world bank/card CSV header shapes.
    show("chase_checking.csv")
    show("bofa_checking.csv")
    show("wells_fargo_checking.csv")
    show("capital_one_creditcard.csv")  # split Debit/Credit columns

    # Amex & Discover report charges as POSITIVE; flip with invert_amount=True
    # (CLI: --invert-amounts) so they land in our debit-negative convention.
    for name in ("amex_creditcard.csv", "discover_creditcard.csv"):
        with open(_path(name), "rb") as fh:
            data = fh.read()
        stmt = normalize_bytes(data, fmt="csv", invert_amount=True)
        print(f"\n# {name}  (csv, inverted)")
        for txn in stmt.transactions:
            print(
                f"  {txn.date}  {txn.amount:>10}  {txn.txn_type.value:<6}  {txn.description}"
            )

    # 2. SWIFT MT940, ISO 20022 CAMT.053, and Quicken QIF.
    show("sample.mt940")
    show("sample.camt053.xml")
    show("sample.qif")

    # 3. Dedup / merge across two overlapping monthly exports.
    #    overlap_feb.csv re-includes the last 3 rows of overlap_jan.csv.
    print("\n" + "=" * 72)
    print("Merge of overlapping monthly exports (cross-statement dedup)")
    print("=" * 72)
    jan = normalize_file(_path("overlap_jan.csv"))
    feb = normalize_file(_path("overlap_feb.csv"))
    merged = normalize_many([_path("overlap_jan.csv"), _path("overlap_feb.csv")])
    print(f"  overlap_jan.csv : {len(jan.transactions)} txns")
    print(f"  overlap_feb.csv : {len(feb.transactions)} txns")
    print(
        f"  merged          : {len(merged)} txns "
        f"(3 duplicate rows collapsed, legitimate same-merchant repeats kept)"
    )


if __name__ == "__main__":
    main()
