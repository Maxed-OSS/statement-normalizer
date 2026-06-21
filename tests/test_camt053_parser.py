import datetime as dt
from decimal import Decimal

import pytest

from statement_normalizer.parsers import camt053_parser
from statement_normalizer.schema import TxnType
from statement_normalizer.util import ParseError


def _read(path):
    with open(path, "rb") as fh:
        return fh.read()


def test_camt053_basic(fixture_path):
    stmt = camt053_parser.parse(_read(fixture_path("sample.camt053.xml")))
    assert stmt.source_format == "camt053"
    assert stmt.currency == "EUR"
    assert stmt.account_id == "NL91ABNA0417164300"
    assert len(stmt.transactions) == 3

    gas = stmt.transactions[0]
    assert gas.date == dt.date(2024, 1, 5)
    assert gas.amount == Decimal("-45.20")  # DBIT -> negative
    assert gas.txn_type == TxnType.DEBIT
    assert gas.description == "CARD PAYMENT GAS STATION 4471"
    assert gas.fitid == "REF1"  # AcctSvcrRef used as FITID-equivalent

    payroll = stmt.transactions[1]
    assert payroll.amount == Decimal("2500.00")  # CRDT -> positive
    assert payroll.txn_type == TxnType.CREDIT


def test_camt053_rejects_other_xml():
    with pytest.raises(ParseError):
        camt053_parser.parse("<Document><Foo>bar</Foo></Document>")


def test_camt053_fitid_dedup_on_merge(fixture_path):
    # Re-parsing the same statement and merging must collapse on AcctSvcrRef.
    from statement_normalizer.dedup import dedup_transactions

    stmt = camt053_parser.parse(_read(fixture_path("sample.camt053.xml")))
    doubled = stmt.transactions + stmt.transactions
    deduped = dedup_transactions(doubled)
    assert len(deduped) == 3
