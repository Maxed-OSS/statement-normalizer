"""CSV statement parser.

Handles the common shapes banks export:

1. Single signed ``Amount`` column.
2. Separate ``Debit`` and ``Credit`` columns.
3. An optional running ``Balance`` column.

Column detection is header-name based (fuzzy, case-insensitive) so it works
across many banks without per-bank configuration. Sign convention: debits are
stored negative, credits positive, regardless of how the source expressed them.
"""

from __future__ import annotations

import csv
import io
from decimal import Decimal
from typing import Optional

from ..schema import NormalizedStatement, Transaction
from ..util import ParseError, first_match, parse_date, parse_money

_DATE_COLS = ("date", "transactiondate", "postingdate", "posteddate", "postdate")
_DESC_COLS = (
    "description",
    "desc",
    "payee",
    "memo",
    "name",
    "details",
    "transaction",
    "narrative",
)
_AMOUNT_COLS = ("amount", "amt", "value")
_DEBIT_COLS = ("debit", "withdrawal", "withdrawals", "debitamount", "moneyout")
_CREDIT_COLS = ("credit", "deposit", "deposits", "creditamount", "moneyin")
_BALANCE_COLS = ("balance", "runningbalance", "bal")
_CURRENCY_COLS = ("currency", "ccy", "currencycode")


def _to_text(data) -> str:
    if isinstance(data, bytes):
        return data.decode("utf-8-sig")
    return data


def parse(data, *, default_currency: str = "USD") -> NormalizedStatement:
    """Parse CSV bytes/str into a NormalizedStatement."""
    text = _to_text(data)
    reader = csv.reader(io.StringIO(text))
    rows = [r for r in reader if any(cell.strip() for cell in r)]
    if not rows:
        return NormalizedStatement(source_format="csv", currency=default_currency)

    header = rows[0]
    body = rows[1:]

    i_date = first_match(header, _DATE_COLS)
    i_desc = first_match(header, _DESC_COLS)
    i_amount = first_match(header, _AMOUNT_COLS)
    i_debit = first_match(header, _DEBIT_COLS)
    i_credit = first_match(header, _CREDIT_COLS)
    i_balance = first_match(header, _BALANCE_COLS)
    i_currency = first_match(header, _CURRENCY_COLS)

    if i_date is None:
        raise ParseError("CSV has no recognizable date column")
    if i_amount is None and i_debit is None and i_credit is None:
        raise ParseError("CSV has no recognizable amount/debit/credit column")

    txns: list[Transaction] = []
    for row in body:
        # Pad short rows so index access is safe.
        if len(row) < len(header):
            row = row + [""] * (len(header) - len(row))

        raw_date = row[i_date].strip()
        if not raw_date:
            continue  # skip subtotal/blank lines
        try:
            date = parse_date(raw_date)
        except ParseError:
            continue  # non-data line (e.g. footer text)

        amount = _resolve_amount(row, i_amount, i_debit, i_credit)
        if amount is None or amount == 0:
            continue  # skip zero-amount lines (opening-balance markers, etc.)

        description = row[i_desc].strip() if i_desc is not None else ""
        balance = _opt_money(row, i_balance)
        currency = (
            row[i_currency].strip().upper()
            if i_currency is not None and row[i_currency].strip()
            else default_currency
        )

        txns.append(
            Transaction.create(
                date=date,
                amount=amount,
                description=description,
                currency=currency,
                balance=balance,
                source_format="csv",
                raw=dict(zip(header, row)),
            )
        )

    return NormalizedStatement(
        transactions=txns,
        currency=default_currency,
        source_format="csv",
    )


def _resolve_amount(
    row: list[str],
    i_amount: Optional[int],
    i_debit: Optional[int],
    i_credit: Optional[int],
) -> Optional[Decimal]:
    """Compute a signed amount from whichever columns the CSV provides."""
    if i_amount is not None and row[i_amount].strip():
        return parse_money(row[i_amount])

    debit = _opt_money(row, i_debit)
    credit = _opt_money(row, i_credit)

    if debit is not None and debit != 0:
        # Debit columns are usually positive magnitudes -> store as negative.
        return -abs(debit)
    if credit is not None and credit != 0:
        return abs(credit)
    return None


def _opt_money(row: list[str], idx: Optional[int]) -> Optional[Decimal]:
    if idx is None:
        return None
    cell = row[idx].strip()
    if not cell:
        return None
    try:
        return parse_money(cell)
    except ParseError:
        return None
