import datetime as dt
from decimal import Decimal

from statement_normalizer.parsers import csv_parser
from statement_normalizer.schema import TxnType


def _read(path):
    with open(path, "rb") as fh:
        return fh.read()


def test_signed_amount_csv(fixture_path):
    stmt = csv_parser.parse(_read(fixture_path("bank_signed_amount.csv")))
    assert stmt.source_format == "csv"
    # 7 rows incl. a zero-amount opening adjustment which is skipped (amount 0).
    descs = [t.description for t in stmt.transactions]
    assert "COFFEE ROASTERS #221" in descs
    assert "OPENING BALANCE ADJUSTMENT" not in descs  # amount 0 -> dropped

    coffee = next(t for t in stmt.transactions if "COFFEE" in t.description)
    assert coffee.amount == Decimal("-4.75")
    assert coffee.txn_type == TxnType.DEBIT
    assert coffee.balance == Decimal("995.25")

    payroll = next(t for t in stmt.transactions if "PAYROLL" in t.description)
    assert payroll.amount == Decimal("2500.00")
    assert payroll.txn_type == TxnType.CREDIT
    assert payroll.date == dt.date(2024, 1, 6)


def test_debit_credit_columns_csv(fixture_path):
    stmt = csv_parser.parse(_read(fixture_path("bank_debit_credit.csv")))
    cafe = next(t for t in stmt.transactions if "RIVERSIDE" in t.description)
    assert cafe.amount == Decimal("-8.50")  # debit -> negative
    salary = next(t for t in stmt.transactions if "SALARY" in t.description)
    assert salary.amount == Decimal("3200.00")  # credit -> positive
    check = next(t for t in stmt.transactions if "CHECK #1042" in t.description)
    assert check.amount == Decimal("-1200.00")
    assert check.balance == Decimal("3845.51")


def test_credit_card_parentheses(fixture_path):
    stmt = csv_parser.parse(_read(fixture_path("creditcard.csv")))
    gas = next(t for t in stmt.transactions if "GAS STATION" in t.description)
    assert gas.amount == Decimal("-45.20")
    payment = next(t for t in stmt.transactions if "PAYMENT" in t.description)
    assert payment.amount == Decimal("250.00")
    assert payment.txn_type == TxnType.CREDIT
