import datetime as dt
from decimal import Decimal

import pytest

from statement_normalizer import normalize_bytes
from statement_normalizer.normalize import detect_format
from statement_normalizer.parsers import camt052_parser
from statement_normalizer.schema import TxnType
from statement_normalizer.util import ParseError


def _read(path):
    with open(path, "rb") as fh:
        return fh.read()


def test_camt052_basic(fixture_path):
    stmt = camt052_parser.parse(_read(fixture_path("sample.camt052.xml")))
    assert stmt.source_format == "camt052"
    assert stmt.currency == "EUR"
    assert stmt.account_id == "NL91ABNA0417164300"
    assert len(stmt.transactions) == 2

    coffee = stmt.transactions[0]
    assert coffee.date == dt.date(2024, 1, 8)
    assert coffee.amount == Decimal("-19.99")  # DBIT -> negative
    assert coffee.txn_type == TxnType.DEBIT
    assert coffee.description == "CARD PAYMENT COFFEE BAR CENTRAL"
    assert coffee.fitid == "IRPT1"

    incoming = stmt.transactions[1]
    assert incoming.amount == Decimal("820.00")  # CRDT -> positive
    assert incoming.txn_type == TxnType.CREDIT


def test_camt052_rejects_camt053(fixture_path):
    # A CAMT.053 statement must not be accepted by the CAMT.052 parser.
    with pytest.raises(ParseError):
        camt052_parser.parse(_read(fixture_path("sample.camt053.xml")))


def test_detect_format_distinguishes_camt052_from_camt053(fixture_path):
    # Both are .xml, so detection must rely on the container element, not the
    # extension. This is the regression guard for the wiring fix.
    c52 = _read(fixture_path("sample.camt052.xml"))
    c53 = _read(fixture_path("sample.camt053.xml"))
    assert detect_format(c52, filename="report.xml") == "camt052"
    assert detect_format(c53, filename="statement.xml") == "camt053"


def test_normalize_bytes_routes_camt052_end_to_end(fixture_path):
    # The top-level API must detect, parse, and dedup a CAMT.052 report without
    # an explicit format override.
    data = _read(fixture_path("sample.camt052.xml"))
    stmt = normalize_bytes(data, filename="intraday.xml")
    assert stmt.source_format == "camt052"
    assert len(stmt.transactions) == 2
