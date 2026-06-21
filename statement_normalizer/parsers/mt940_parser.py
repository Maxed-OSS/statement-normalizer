"""MT940 statement parser.

MT940 is the SWIFT bank-statement message format. Many banks (especially in
Europe) let you export account statements as MT940 ``.sta`` / ``.940`` files.
A statement is a flat sequence of colon-delimited tags::

    :20:STARTUMS
    :25:1234567890
    :60F:C240101EUR1000,00
    :61:2401050105D45,20NTRFNONREF
    :86:CARD PAYMENT GAS STATION 4471
    :62F:C240131EUR2540,30

We parse it with a small deterministic tokenizer (no external MT940 library).

Tags we use:

* ``:25:``  account identification -> ``account_id``
* ``:60F:`` / ``:60M:`` opening balance -> seeds the currency (``CURDEF``-like)
* ``:61:``  statement line: value date, D/C mark, amount, transaction ref
* ``:86:``  information-to-account-owner: free-text description for the prior
  ``:61:`` line.

Sign convention: the MT940 ``D``/``C`` debit/credit mark on each ``:61:`` line
is mapped to our signed convention (D -> negative, C -> positive). MT940 amounts
use a comma decimal separator, which we normalize.
"""

from __future__ import annotations

import datetime as _dt
import re
from decimal import Decimal
from typing import Optional

from ..schema import NormalizedStatement, Transaction
from ..util import ParseError

# A field is ``:TAG:value`` where value may span continuation lines until the
# next ``:TAG:`` at the start of a line.
_FIELD_RE = re.compile(r"^:(\d{2}[A-Z]?):(.*)$")

# :61: subfield layout (the part we need, left-anchored):
#   6!n value date  (YYMMDD)
#   [4!n entry date (MMDD)]      -- optional
#   2a  D/C mark    (D, C, RD, RC)
#   [1!a funds code]            -- optional single letter
#   15d amount      (digits + comma decimal)
# We capture value date, the D/C mark, and the amount magnitude.
_61_RE = re.compile(
    r"^(?P<valuedate>\d{6})"
    r"(?P<entrydate>\d{4})?"
    r"(?P<dcmark>R?[DC])"
    r"(?P<fundscode>[A-Z])?"
    r"(?P<amount>[\d,]+)"
)


def _to_text(data) -> str:
    if isinstance(data, bytes):
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return data.decode("latin-1")
    return data


def looks_like_mt940(text: str) -> bool:
    """Heuristic: MT940 has :20: / :25: / :61: tags at line starts."""
    head = text[:2048]
    has_61 = bool(re.search(r"^:61:", head, re.MULTILINE))
    has_2x = bool(re.search(r"^:2[05]:", head, re.MULTILINE))
    return has_61 and has_2x


def _iter_fields(text: str):
    """Yield (tag, value) honoring continuation lines."""
    tag: Optional[str] = None
    buf: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.rstrip("\r")
        if line.strip() == "-":  # end-of-message marker
            continue
        m = _FIELD_RE.match(line)
        if m:
            if tag is not None:
                yield tag, "\n".join(buf)
            tag = m.group(1)
            buf = [m.group(2)]
        elif tag is not None:
            buf.append(line)
    if tag is not None:
        yield tag, "\n".join(buf)


def _parse_value_date(yymmdd: str) -> _dt.date:
    year = 2000 + int(yymmdd[0:2])
    month = int(yymmdd[2:4])
    day = int(yymmdd[4:6])
    try:
        return _dt.date(year, month, day)
    except ValueError as exc:
        raise ParseError(f"invalid MT940 date: {yymmdd!r}") from exc


def _parse_mt940_amount(raw: str) -> Decimal:
    """MT940 amounts use a comma decimal separator, no thousands separators."""
    cleaned = raw.strip().replace(",", ".")
    try:
        return Decimal(cleaned)
    except Exception as exc:  # pragma: no cover - defensive
        raise ParseError(f"unparseable MT940 amount: {raw!r}") from exc


def parse(data, *, default_currency: str = "USD") -> NormalizedStatement:
    """Parse MT940 bytes/str into a NormalizedStatement."""
    text = _to_text(data)
    if not looks_like_mt940(text):
        raise ParseError("input does not look like MT940")

    account_id: Optional[str] = None
    currency: Optional[str] = None
    txns: list[Transaction] = []

    pending: Optional[dict] = None  # the :61: line awaiting its :86: description

    def flush(desc: str = "") -> None:
        nonlocal pending
        if pending is None:
            return
        txns.append(
            Transaction.create(
                date=pending["date"],
                amount=pending["amount"],
                description=desc.strip(),
                currency=currency or default_currency,
                account_id=account_id,
                source_format="mt940",
                raw={"tag61": pending["raw61"]},
            )
        )
        pending = None

    for tag, value in _iter_fields(text):
        base = tag[:2]
        if base == "25":
            account_id = value.strip() or account_id
        elif base == "60" or base == "62":
            # Opening/closing balance: C/Dyymmddccc...; pull the currency.
            cur_match = re.search(r"^[CD]\d{6}([A-Z]{3})", value.strip())
            if cur_match and currency is None:
                currency = cur_match.group(1)
        elif base == "61":
            flush()  # close out any previous line lacking an :86:
            m = _61_RE.match(value.strip())
            if not m:
                continue
            date = _parse_value_date(m.group("valuedate"))
            magnitude = _parse_mt940_amount(m.group("amount"))
            negative = m.group("dcmark") in ("D", "RC")  # RC = reversal of credit
            amount = -magnitude if negative else magnitude
            # ``//`` separates bank ref from the supplementary details / NONREF.
            ref_tail = value.split("\n", 1)[0]
            pending = {
                "date": date,
                "amount": amount,
                "raw61": ref_tail.strip(),
            }
        elif base == "86":
            flush(value.replace("\n", " "))

    flush()  # trailing line with no :86:

    return NormalizedStatement(
        transactions=txns,
        account_id=account_id,
        currency=currency or default_currency,
        source_format="mt940",
    )
