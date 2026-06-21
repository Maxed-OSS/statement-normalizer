import datetime as dt
from decimal import Decimal

from statement_normalizer.parsers import text_parser
from statement_normalizer.schema import TxnType


def _read(path):
    with open(path, "rb") as fh:
        return fh.read()


def test_text_statement(fixture_path):
    stmt = text_parser.parse(_read(fixture_path("statement.txt")))
    assert stmt.source_format == "text"

    descs = [t.description for t in stmt.transactions]
    assert "COFFEE ROASTERS #221" in descs
    # Header/footer lines must not be parsed as transactions.
    assert all("Page 1" not in d for d in descs)
    assert all("Thank you" not in d for d in descs)

    coffee = next(t for t in stmt.transactions if "COFFEE" in t.description)
    assert coffee.date == dt.date(2024, 1, 5)
    assert coffee.amount == Decimal("-4.75")
    assert coffee.balance == Decimal("1995.25")
    assert coffee.txn_type == TxnType.DEBIT

    payroll = next(t for t in stmt.transactions if "PAYROLL" in t.description)
    assert payroll.amount == Decimal("2500.00")
    assert payroll.balance == Decimal("4495.25")


def test_text_no_balance_column():
    text = (
        "01/05/2024 COFFEE SHOP -4.75\n"
        "01/06/2024 PAYDAY 2500.00\n"
    )
    stmt = text_parser.parse(text)
    assert len(stmt.transactions) == 2
    coffee = stmt.transactions[0]
    assert coffee.amount == Decimal("-4.75")
    assert coffee.balance is None
