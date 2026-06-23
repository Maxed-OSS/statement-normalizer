import datetime as dt
from decimal import Decimal

import pytest

from statement_normalizer.normalize import detect_format, normalize_bytes
from statement_normalizer.parsers import qif_parser
from statement_normalizer.schema import TxnType
from statement_normalizer.util import ParseError


def _read(path):
    with open(path, "rb") as fh:
        return fh.read()


def test_qif_basic(fixture_path):
    stmt = qif_parser.parse(_read(fixture_path("sample.qif")))
    assert stmt.source_format == "qif"
    assert stmt.currency == "USD"
    assert len(stmt.transactions) == 4

    gas = stmt.transactions[0]
    assert gas.date == dt.date(2024, 2, 1)
    assert gas.amount == Decimal("-45.20")  # signed at source -> negative
    assert gas.txn_type == TxnType.DEBIT
    # Payee + memo joined, mirroring the OFX parser's NAME + MEMO behavior.
    assert gas.description == "GAS STATION 4471 Fuel regular unleaded"
    assert gas.fitid == "1021"  # N (check/ref number) preserved as a dedup hint
    assert gas.raw["L"] == "Auto:Fuel"  # category retained on raw


def test_qif_credit_with_thousands_separator(fixture_path):
    stmt = qif_parser.parse(_read(fixture_path("sample.qif")))
    payroll = stmt.transactions[1]
    assert payroll.amount == Decimal("2500.00")  # "2,500.00"
    assert payroll.txn_type == TxnType.CREDIT


def test_qif_apostrophe_year_and_u_amount_fallback(fixture_path):
    stmt = qif_parser.parse(_read(fixture_path("sample.qif")))
    wire = stmt.transactions[3]
    # Date written as 02/20'24 (apostrophe year) and amount only in the U field.
    assert wire.date == dt.date(2024, 2, 20)
    assert wire.amount == Decimal("-1234.56")
    assert wire.description == "WIRE TO VENDOR"


def test_qif_detection_by_content_and_extension(fixture_path):
    data = _read(fixture_path("sample.qif"))
    assert detect_format(data) == "qif"
    assert detect_format(b"Date,Amount\n2024-01-01,1.00", filename="x.qif") == "qif"


def test_qif_end_to_end_via_normalize(fixture_path):
    stmt = normalize_bytes(_read(fixture_path("sample.qif")), fmt="qif")
    assert stmt.source_format == "qif"
    assert len(stmt.transactions) == 4


def test_qif_skips_non_statement_sections():
    # An !Account list block and a category list should not yield transactions;
    # only the !Type:Bank records do.
    text = (
        "!Account\n"
        "NChecking\n"
        "TBank\n"
        "^\n"
        "!Type:Cat\n"
        "NGroceries\n"
        "^\n"
        "!Type:Bank\n"
        "D01/15/2024\n"
        "T-10.00\n"
        "PCOFFEE SHOP\n"
        "^\n"
    )
    stmt = qif_parser.parse(text)
    assert len(stmt.transactions) == 1
    assert stmt.transactions[0].description == "COFFEE SHOP"


def test_qif_ccard_type_is_a_statement():
    text = "!Type:CCard\nD01/02/2024\nT-19.99\nPSTREAMING SERVICE\n^\n"
    stmt = qif_parser.parse(text)
    assert stmt.source_format == "qif"
    assert len(stmt.transactions) == 1
    assert stmt.transactions[0].amount == Decimal("-19.99")


def test_qif_default_currency_override():
    text = "!Type:Bank\nD01/02/2024\nT-19.99\nPSHOP\n^\n"
    stmt = qif_parser.parse(text, default_currency="eur")
    assert stmt.currency == "EUR"
    assert stmt.transactions[0].currency == "EUR"


def test_qif_malformed_record_is_skipped():
    # A record missing a date is dropped; the well-formed one survives.
    text = "!Type:Bank\nT-5.00\nPNO DATE HERE\n^\nD01/03/2024\nT-7.00\nPGOOD\n^\n"
    stmt = qif_parser.parse(text)
    assert [t.description for t in stmt.transactions] == ["GOOD"]


def test_qif_rejects_non_qif():
    with pytest.raises(ParseError):
        qif_parser.parse("Date,Description,Amount\n2024-01-01,FOO,1.00\n")


def test_qif_looks_like():
    assert qif_parser.looks_like_qif("!Type:Bank\nD01/01/2024\nT1.00\n^\n")
    assert qif_parser.looks_like_qif("\n\n!Account\nNChecking\n")
    assert not qif_parser.looks_like_qif("just some text")
