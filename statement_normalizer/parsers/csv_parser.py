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
from ..util import ParseError, all_matches, first_match, parse_date, parse_money

# Header aliases are matched fuzzily (lowercased, alphanumerics only) so the
# real-world variations exported by major banks resolve without per-bank config.
# The comments below note which banks/cards a given alias is drawn from.
_DATE_COLS = (
    "date",
    "transactiondate",  # Chase, Capital One, Amex
    "postingdate",  # Chase, BofA
    "posteddate",  # Wells Fargo
    "postdate",
    "posteddate",
    "transdate",
    "transactiondateposted",
    "datemmddyyyy",
    "effectivedate",  # Discover
    "processdate",
)
_DESC_COLS = (
    "description",  # Chase, BofA, Capital One, Discover
    "desc",
    "payee",  # Wells Fargo / Quicken-style
    "memo",  # OFX-derived CSVs
    "name",
    "details",
    "transaction",
    "narrative",  # many UK / international banks
    "originaldescription",  # Mint / Capital One export
    "merchant",  # Amex "Merchant"
    "extendeddetails",  # Amex
    "transactiondetails",
    "appearsonyourstatementas",  # Amex literal header
    "reference",
)
_AMOUNT_COLS = (
    "amount",  # Chase, Capital One (signed), Amex
    "amt",
    "value",
    "transactionamount",
    "amountusd",
    "netamount",
)
_DEBIT_COLS = (
    "debit",  # BofA-style split columns
    "withdrawal",
    "withdrawals",  # Wells Fargo
    "withdrawalamount",
    "debitamount",
    "moneyout",  # many UK banks
    "paymentsandcredits",  # (handled below; Amex sometimes inverts)
    "charges",
    "debits",
)
_CREDIT_COLS = (
    "credit",  # BofA-style split columns
    "deposit",
    "deposits",  # Wells Fargo
    "depositamount",
    "creditamount",
    "moneyin",  # many UK banks
    "credits",
    "payments",
)
_BALANCE_COLS = (
    "balance",  # Wells Fargo, BofA
    "runningbalance",
    "bal",
    "runningbal",
    "balanceamount",
    "currentbalance",
)
_CURRENCY_COLS = ("currency", "ccy", "currencycode", "transactioncurrency")

# Some issuers (notably Capital One on its "Debit"/"Credit" export) emit BOTH a
# Debit and a Credit column where Debit holds positive spend and Credit holds
# positive payments. Others (older Amex CSVs) report charges as POSITIVE in a
# single Amount column. We keep sign handling in ``_resolve_amount`` purely
# data-driven (magnitude of whichever column is populated) so no issuer-specific
# branching is needed.


def _to_text(data) -> str:
    if isinstance(data, bytes):
        return data.decode("utf-8-sig")
    return data


def parse(
    data,
    *,
    default_currency: str = "USD",
    invert_amount: bool = False,
) -> NormalizedStatement:
    """Parse CSV bytes/str into a NormalizedStatement.

    ``invert_amount`` flips the sign of every parsed amount. This is needed for
    issuers (e.g. some credit-card exports) that report **charges as positive**
    and **payments as negative** in a single signed ``Amount`` column, which is
    the inverse of this library's convention (debits negative, credits positive).
    It only affects the single-``Amount``-column path; split debit/credit columns
    already carry unambiguous direction.
    """
    text = _to_text(data)
    reader = csv.reader(io.StringIO(text))
    rows = [r for r in reader if any(cell.strip() for cell in r)]
    if not rows:
        return NormalizedStatement(source_format="csv", currency=default_currency)

    header = rows[0]
    body = rows[1:]

    i_date = first_match(header, _DATE_COLS)
    # Some banks (e.g. Wells Fargo) leave the primary description column ("Payee")
    # blank and put the real text in a secondary one ("Memo"). Collect every
    # matching description column so we can fall back to the first non-empty.
    desc_cols = all_matches(header, _DESC_COLS)
    i_desc = desc_cols[0] if desc_cols else None
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
        # Only invert the single signed-Amount path; split debit/credit columns
        # already encode direction unambiguously.
        if invert_amount and i_amount is not None and row[i_amount].strip():
            amount = -amount

        description = _resolve_description(row, desc_cols)
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


def _resolve_description(row: list[str], desc_cols: list[int]) -> str:
    """First non-empty value across all matched description columns."""
    for idx in desc_cols:
        if idx < len(row):
            cell = row[idx].strip()
            if cell:
                return cell
    return ""


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
