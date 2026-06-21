"""Deterministic dedup heuristics for normalized transactions.

Two reasons duplicates arise:

1. Overlapping exports — you download Jan and Jan-Feb statements; the same rows
   appear in both.
2. Re-imports — the same file is processed twice.

Strategy (in priority order, fully deterministic):

* If two transactions share a non-empty ``fitid`` (and account), they are the
  same transaction. FITID is bank-assigned and authoritative.
* Otherwise fall back to a content hash over (date, signed amount, currency,
  canonical description). To avoid collapsing genuinely-repeated charges (e.g.
  two identical $4.75 coffees on the same day), identical content rows are only
  treated as duplicates beyond the count seen on a *single* source statement —
  i.e. we keep the max multiplicity observed within any one input, not the sum.

The first occurrence is kept; order is otherwise preserved (stable).
"""

from __future__ import annotations

from collections import Counter
from typing import Iterable, Optional

from .schema import Transaction


def dedup_transactions(
    transactions: Iterable[Transaction],
    *,
    per_source_multiplicity: Optional[dict[str, int]] = None,
) -> list[Transaction]:
    """Return a de-duplicated, order-stable list of transactions.

    ``per_source_multiplicity`` optionally maps a content hash to the maximum
    number of legitimate copies seen within a single source statement. When
    provided, that many copies are preserved before extras are dropped. When
    omitted, content-hash duplicates collapse to a single row (FITID matches
    always collapse to one).
    """
    fitid_seen: set[tuple[str, str]] = set()
    content_kept: Counter[str] = Counter()
    out: list[Transaction] = []

    for txn in transactions:
        if txn.fitid:
            key = (txn.account_id or "", txn.fitid)
            if key in fitid_seen:
                continue
            fitid_seen.add(key)
            out.append(txn)
            continue

        chash = txn.content_hash()
        allowed = 1
        if per_source_multiplicity is not None:
            allowed = max(1, per_source_multiplicity.get(chash, 1))

        if content_kept[chash] >= allowed:
            continue
        content_kept[chash] += 1
        out.append(txn)

    return out


def source_multiplicity(transactions: Iterable[Transaction]) -> dict[str, int]:
    """Count content-hash multiplicity within a single source statement.

    Feed the transactions of ONE statement; the result can be passed as
    ``per_source_multiplicity`` to :func:`dedup_transactions` so that legitimate
    same-day repeated charges within that statement are preserved across a
    cross-statement merge.
    """
    counts: Counter[str] = Counter()
    for txn in transactions:
        if not txn.fitid:
            counts[txn.content_hash()] += 1
    return dict(counts)
