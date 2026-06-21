import datetime as dt
from decimal import Decimal

import pytest

from statement_normalizer.util import (
    ParseError,
    parse_date,
    parse_money,
    parse_ofx_date,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2024-01-05", dt.date(2024, 1, 5)),
        ("01/05/2024", dt.date(2024, 1, 5)),
        ("1/5/24", dt.date(2024, 1, 5)),
        ("05-Jan-2024", dt.date(2024, 1, 5)),
        ("20240105", dt.date(2024, 1, 5)),
    ],
)
def test_parse_date_formats(raw, expected):
    assert parse_date(raw) == expected


def test_parse_date_rejects_garbage():
    with pytest.raises(ParseError):
        parse_date("not-a-date")


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("4.75", Decimal("4.75")),
        ("-4.75", Decimal("-4.75")),
        ("$1,234.56", Decimal("1234.56")),
        ("(1,234.56)", Decimal("-1234.56")),
        ("100.00-", Decimal("-100.00")),
        ("+50.00", Decimal("50.00")),
        ("  $ 2,500.00 ", Decimal("2500.00")),
    ],
)
def test_parse_money(raw, expected):
    assert parse_money(raw) == expected


def test_parse_money_rejects_empty():
    with pytest.raises(ParseError):
        parse_money("")


def test_parse_ofx_date_with_and_without_time():
    assert parse_ofx_date("20240105120000") == dt.date(2024, 1, 5)
    assert parse_ofx_date("20240105") == dt.date(2024, 1, 5)
    assert parse_ofx_date("20240105120000[-5:EST]") == dt.date(2024, 1, 5)
