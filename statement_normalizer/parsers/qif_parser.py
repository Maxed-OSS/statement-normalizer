"""QIF (Quicken Interchange Format) statement parser.

QIF is the long-lived plain-text export format used by Quicken and many banks,
credit unions, and personal-finance tools. A QIF file opens with a ``!Type:``
header naming the account flavor, followed by one record per transaction. Each
record is a set of single-letter field lines terminated by a ``^`` line::

    !Type:Bank
    D02/05/2024
    T-45.20
    PGAS STATION 4471
    MFuel, regular unleaded
    ^
    D02/06/2024
    T250.00
    PPAYMENT - THANK YOU
    ^

We parse it with a small deterministic tokenizer (no external QIF library).

Fields we use:

* ``D``  date (US ``MM/DD/YY[YY]`` is the common dialect; ISO dates are also
  accepted via the shared date parser).
* ``T`` / ``U``  amount. QIF amounts are already signed (debits negative,
  credits positive), which matches our schema. ``U`` is a duplicate of ``T`` in
  some dialects and is used only as a fallback.
* ``P``  payee, and ``M`` memo. We join them into the description, mirroring how
  the OFX parser combines ``NAME`` + ``MEMO``.
* ``N``  the check or reference number, preserved on ``raw`` and used as a dedup
  hint when present.
* ``L``  the Quicken category/transfer line, preserved on ``raw`` for
  traceability.

Sign convention: QIF amounts are signed at the source, so we preserve them
as-is. A leading apostrophe form (Excel-style) and comma thousands separators
are both handled by the shared money parser.
"""

from __future__ import annotations

from typing import Optional

from ..schema import NormalizedStatement, Transaction
from ..util import ParseError, parse_date, parse_money

# QIF account-type headers we recognise as bank/card statements. QIF also has
# investment ("!Type:Invst") and list ("!Account", "!Type:Cat") sections that
# are not transaction statements; we skip those rather than guess.
_STATEMENT_TYPES = {
    "bank",
    "ccard",
    "cash",
    "oth a",  # other asset
    "oth l",  # other liability
}


def _to_text(data) -> str:
    if isinstance(data, bytes):
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return data.decode("latin-1")
    return data


def looks_like_qif(text: str) -> bool:
    """Heuristic: a QIF file starts with a ``!Type:`` (or ``!Account``) header."""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        upper = line.upper()
        return upper.startswith("!TYPE:") or upper.startswith("!ACCOUNT")
    return False


def _account_type(header: str) -> Optional[str]:
    """Return the lower-cased account flavor from a ``!Type:Bank`` header line."""
    if ":" not in header:
        return None
    return header.split(":", 1)[1].strip().lower()


def _parse_date(value: str) -> "object":
    """Parse a QIF date.

    QIF most often uses ``M/D'YY`` or ``M/D/YYYY`` with ``'`` separating the
    year in older dialects. We normalise the apostrophe to a slash and defer to
    the shared, deterministic date parser so every format the rest of the
    library accepts works here too.
    """
    cleaned = value.strip().replace("'", "/").replace(" ", "")
    return parse_date(cleaned)


def parse(data, *, default_currency: str = "USD") -> NormalizedStatement:
    """Parse QIF bytes/str into a NormalizedStatement."""
    text = _to_text(data)
    if not looks_like_qif(text):
        raise ParseError("input does not look like QIF")

    currency = (default_currency or "USD").upper()
    txns: list[Transaction] = []

    # State for the in-progress record.
    in_statement = False
    record: dict[str, str] = {}

    def flush() -> None:
        nonlocal record
        if not record:
            return
        date_raw = record.get("D")
        amount_raw = record.get("T") or record.get("U")
        if date_raw is None or amount_raw is None:
            record = {}
            return
        try:
            date = _parse_date(date_raw)
            amount = parse_money(amount_raw)
        except ParseError:
            # A malformed record is skipped rather than aborting the whole file;
            # this mirrors how the OFX/MT940 parsers tolerate partial lines.
            record = {}
            return
        payee = record.get("P", "")
        memo = record.get("M", "")
        description = " ".join(p for p in (payee, memo) if p).strip()
        raw = {k: v for k, v in record.items()}
        txns.append(
            Transaction.create(
                date=date,
                amount=amount,
                description=description,
                currency=currency,
                fitid=record.get("N") or None,
                source_format="qif",
                raw=raw,
            )
        )
        record = {}

    for raw_line in text.splitlines():
        line = raw_line.rstrip("\r")
        if not line.strip():
            continue
        if line.startswith("!"):
            # A new section header. Decide whether the records that follow are
            # statement transactions we should keep.
            flush()
            atype = _account_type(line)
            if line.strip().upper().startswith("!ACCOUNT"):
                # !Account blocks describe accounts, not transactions; skip until
                # the next !Type: header.
                in_statement = False
            else:
                in_statement = atype in _STATEMENT_TYPES if atype else False
            continue
        if not in_statement:
            continue
        if line.startswith("^"):
            flush()
            continue
        code, value = line[0], line[1:].strip()
        if code in record and code in ("M", "P"):
            # Some dialects emit a split payee/memo across lines; concatenate.
            record[code] = f"{record[code]} {value}".strip()
        else:
            record[code] = value

    flush()  # trailing record with no closing ^

    return NormalizedStatement(
        transactions=txns,
        account_id=None,
        currency=currency,
        source_format="qif",
    )
