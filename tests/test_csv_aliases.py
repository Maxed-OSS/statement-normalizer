"""Coverage for the broadened real-world bank/card CSV header shapes."""

from decimal import Decimal

from statement_normalizer.parsers import csv_parser
from statement_normalizer.schema import TxnType


def _read(path):
    with open(path, "rb") as fh:
        return fh.read()


def test_wells_fargo_memo_description_fallback(fixture_path):
    # Wells Fargo leaves "Payee" blank and puts the text in "Memo"; the parser
    # must fall back to the first non-empty description column.
    stmt = csv_parser.parse(_read(fixture_path("wells_fargo_checking.csv")))
    descs = [t.description for t in stmt.transactions]
    assert all(d for d in descs), descs
    assert any("GAS STATION 4471" in d for d in descs)
    check = next(t for t in stmt.transactions if "CHECK" in t.description)
    assert check.amount == Decimal("-1200.00")


def test_capital_one_split_debit_credit(fixture_path):
    stmt = csv_parser.parse(_read(fixture_path("capital_one_creditcard.csv")))
    gas = next(t for t in stmt.transactions if "GAS STATION" in t.description)
    assert gas.amount == Decimal("-45.20")  # Debit column -> negative
    payment = next(t for t in stmt.transactions if "PAYMENT" in t.description)
    assert payment.amount == Decimal("250.00")  # Credit column -> positive
    assert payment.txn_type == TxnType.CREDIT


def test_amex_invert_amounts(fixture_path):
    # Amex reports charges as positive / payments as negative. Without inversion
    # a charge would wrongly read as a credit; with it, charges become debits.
    raw = _read(fixture_path("amex_creditcard.csv"))

    not_inverted = csv_parser.parse(raw)
    gas = next(t for t in not_inverted.transactions if "GAS STATION" in t.description)
    assert gas.txn_type == TxnType.CREDIT  # raw Amex sign convention

    inverted = csv_parser.parse(raw, invert_amount=True)
    gas2 = next(t for t in inverted.transactions if "GAS STATION" in t.description)
    assert gas2.amount == Decimal("-45.20")
    assert gas2.txn_type == TxnType.DEBIT
    payment = next(t for t in inverted.transactions if "PAYMENT" in t.description)
    assert payment.amount == Decimal("250.00")
    assert payment.txn_type == TxnType.CREDIT
