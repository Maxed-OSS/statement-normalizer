"""Plain-text / PDF-text statement parser.

This handles the common case where a PDF statement has already been run through
a text extractor (e.g. ``pdftotext``) and you have line-oriented text like::

    01/05/2024  COFFEE ROASTERS #221           -4.75      1,020.10
    01/06/2024  PAYROLL DEPOSIT             2,500.00      3,520.10

The parser is line-based and deterministic. Each line must start with a date
token; the trailing number(s) are interpreted as ``amount`` and an optional
running ``balance``. Lines that don't start with a recognizable date are
skipped (headers, page numbers, footers).

We do NOT do PDF binary decoding here — that is intentionally out of scope. Pipe
your PDF through a text extractor first, then feed the text in. This keeps the
library dependency-free and fully deterministic.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Optional

from ..schema import NormalizedStatement, Transaction
from ..util import ParseError, parse_date

# Leading date token: many common separators / month-name styles.
_DATE_TOKEN_RE = re.compile(
    r"^\s*("
    r"\d{4}[-/]\d{1,2}[-/]\d{1,2}"  # 2024-01-05
    r"|\d{1,2}[-/]\d{1,2}[-/]\d{2,4}"  # 01/05/2024
    r"|\d{1,2}-[A-Za-z]{3}-\d{2,4}"  # 05-Jan-2024
    r")\s+(.*)$"
)

# A money token anywhere: optional $, thousands, decimals, optional sign/parens.
_MONEY_TOKEN_RE = re.compile(
    r"\(?[-+]?\$?\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?\)?-?"
)

# Trailing 1 or 2 money tokens at the end of a line.
_TRAILING_MONEY_RE = re.compile(
    r"(?P<amount>\(?[-+]?\$?\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?\)?-?)"
    r"(?:\s+(?P<balance>\(?[-+]?\$?\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?\)?-?))?"
    r"\s*$"
)


def _to_text(data) -> str:
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    return data


def _parse_money_token(token: str) -> Decimal:
    from ..util import parse_money

    return parse_money(token)


def parse(
    data,
    *,
    default_currency: str = "USD",
    has_balance_column: Optional[bool] = None,
) -> NormalizedStatement:
    """Parse line-oriented statement text into a NormalizedStatement.

    ``has_balance_column`` forces interpretation of the last trailing number as
    a running balance (``True``) or as part of the amount (``False``). When
    ``None`` (default), it is auto-detected: if the majority of data lines carry
    two trailing numbers, the last is treated as a balance.
    """
    text = _to_text(data)
    lines = text.splitlines()

    # First pass: identify candidate data lines and how many trailing numbers.
    parsed_lines: list[tuple[str, str, Optional[str], Optional[str]]] = []
    two_count = 0
    for line in lines:
        m = _DATE_TOKEN_RE.match(line)
        if not m:
            continue
        date_token, rest = m.group(1), m.group(2)
        trail = _TRAILING_MONEY_RE.search(rest)
        if not trail:
            continue
        amount_tok = trail.group("amount")
        balance_tok = trail.group("balance")
        if balance_tok is not None:
            two_count += 1
        desc = rest[: trail.start()].strip()
        parsed_lines.append((date_token, desc, amount_tok, balance_tok))

    if has_balance_column is None:
        # Heuristic: treat second number as balance only if most lines have two.
        has_balance_column = bool(parsed_lines) and two_count >= (len(parsed_lines) / 2)

    txns: list[Transaction] = []
    for date_token, desc, amount_tok, balance_tok in parsed_lines:
        try:
            date = parse_date(date_token)
        except ParseError:
            continue

        if has_balance_column and balance_tok is not None:
            amount = _parse_money_token(amount_tok)
            balance = _parse_money_token(balance_tok)
        elif not has_balance_column and balance_tok is not None:
            # Two numbers but no balance column => the "amount" was actually the
            # description tail; the real amount is the last token.
            amount = _parse_money_token(balance_tok)
            balance = None
            desc = (desc + " " + amount_tok).strip()
        else:
            amount = _parse_money_token(amount_tok)
            balance = None

        if amount == 0:
            continue  # skip zero-amount lines (opening-balance markers, etc.)

        txns.append(
            Transaction.create(
                date=date,
                amount=amount,
                description=desc,
                currency=default_currency,
                balance=balance,
                source_format="text",
                raw={"line_desc": desc},
            )
        )

    return NormalizedStatement(
        transactions=txns,
        currency=default_currency,
        source_format="text",
    )
