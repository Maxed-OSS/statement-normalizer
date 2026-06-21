import datetime as dt
from decimal import Decimal

from statement_normalizer.parsers import ofx_parser
from statement_normalizer.schema import TxnType


def _read(path):
    with open(path, "rb") as fh:
        return fh.read()


def test_ofx_basic(fixture_path):
    stmt = ofx_parser.parse(_read(fixture_path("sample.ofx")))
    assert stmt.source_format == "ofx"
    assert stmt.account_id == "000111222333"
    assert stmt.currency == "USD"
    assert len(stmt.transactions) == 3

    coffee = stmt.transactions[0]
    assert coffee.date == dt.date(2024, 1, 5)
    assert coffee.amount == Decimal("-4.75")
    assert coffee.txn_type == TxnType.DEBIT
    assert coffee.fitid == "20240105-0001"
    assert "COFFEE ROASTERS #221" in coffee.description
    assert "CARD PURCHASE" in coffee.description  # NAME + MEMO joined

    payroll = stmt.transactions[1]
    assert payroll.amount == Decimal("2500.00")
    assert payroll.txn_type == TxnType.CREDIT
    assert payroll.account_id == "000111222333"
