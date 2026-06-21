import datetime as dt
from decimal import Decimal

import pytest

from statement_normalizer.parsers import mt940_parser
from statement_normalizer.schema import TxnType
from statement_normalizer.util import ParseError


def _read(path):
    with open(path, "rb") as fh:
        return fh.read()


def test_mt940_basic(fixture_path):
    stmt = mt940_parser.parse(_read(fixture_path("sample.mt940")))
    assert stmt.source_format == "mt940"
    assert stmt.currency == "EUR"
    assert stmt.account_id == "NL91ABNA0417164300"
    assert len(stmt.transactions) == 4

    gas = stmt.transactions[0]
    assert gas.date == dt.date(2024, 1, 5)
    assert gas.amount == Decimal("-45.20")  # D mark -> negative
    assert gas.txn_type == TxnType.DEBIT
    assert gas.description == "CARD PAYMENT GAS STATION 4471"

    payroll = stmt.transactions[1]
    assert payroll.amount == Decimal("2500.00")  # C mark -> positive
    assert payroll.txn_type == TxnType.CREDIT


def test_mt940_comma_decimal(fixture_path):
    stmt = mt940_parser.parse(_read(fixture_path("sample.mt940")))
    big = stmt.transactions[3]
    # MT940 amount "1234,56" with a comma decimal separator.
    assert big.amount == Decimal("-1234.56")


def test_mt940_rejects_non_mt940():
    with pytest.raises(ParseError):
        mt940_parser.parse("Date,Description,Amount\n2024-01-01,FOO,1.00\n")


def test_mt940_looks_like():
    assert mt940_parser.looks_like_mt940(":20:X\n:25:ACC\n:61:2401010101D1,00NTRF\n")
    assert not mt940_parser.looks_like_mt940("just some text")
