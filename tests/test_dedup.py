import datetime as dt
from decimal import Decimal

from statement_normalizer.dedup import dedup_transactions, source_multiplicity
from statement_normalizer.schema import Transaction


def _txn(day, amount, desc, fitid=None, acct=None):
    return Transaction.create(
        date=dt.date(2024, 1, day),
        amount=Decimal(amount),
        description=desc,
        fitid=fitid,
        account_id=acct,
    )


def test_fitid_dedup():
    a = _txn(5, "-4.75", "COFFEE", fitid="X1", acct="A")
    b = _txn(5, "-4.75", "COFFEE", fitid="X1", acct="A")  # exact dup
    c = _txn(6, "-9.00", "LUNCH", fitid="X2", acct="A")
    out = dedup_transactions([a, b, c])
    assert len(out) == 2
    assert {t.fitid for t in out} == {"X1", "X2"}


def test_content_dedup_collapses_without_multiplicity():
    a = _txn(5, "-4.75", "COFFEE ROASTERS")
    b = _txn(5, "-4.75", "Coffee   Roasters")  # same after canonicalization
    out = dedup_transactions([a, b])
    assert len(out) == 1


def test_content_dedup_preserves_legit_repeats_within_source():
    # Two identical coffees on the same day within ONE statement are legitimate.
    a = _txn(5, "-4.75", "COFFEE")
    b = _txn(5, "-4.75", "COFFEE")
    single_source = [a, b]
    mult = source_multiplicity(single_source)
    # Merge that source with itself (simulating overlap re-import).
    merged = single_source + [_txn(5, "-4.75", "COFFEE"), _txn(5, "-4.75", "COFFEE")]
    out = dedup_transactions(merged, per_source_multiplicity=mult)
    # Keep the 2 legitimate copies, drop the 2 overlap copies.
    assert len(out) == 2


def test_order_is_stable():
    txns = [_txn(d, "-1.00", f"D{d}") for d in (3, 1, 2)]
    out = dedup_transactions(txns)
    assert [t.date.day for t in out] == [3, 1, 2]
