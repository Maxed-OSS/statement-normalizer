"""OFX / QFX statement parser.

OFX is SGML-ish: tags often aren't closed. We parse it with a small,
deterministic tokenizer rather than a strict XML library so both OFX 1.x
(SGML) and OFX 2.x (XML) export styles work. No external dependencies.

Sign convention: OFX ``TRNAMT`` is already signed (debits negative, credits
positive), which matches our schema, so we preserve it as-is.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Optional

from ..schema import NormalizedStatement, Transaction
from ..util import ParseError, parse_money, parse_ofx_date

# Match <TAG>value  (value runs until the next '<' or end of line).
_TAG_RE = re.compile(r"<([A-Z0-9.]+)>([^<\r\n]*)")
_STMTTRN_OPEN = "<STMTTRN>"
_STMTTRN_CLOSE = "</STMTTRN>"


def _to_text(data) -> str:
    if isinstance(data, bytes):
        # OFX headers are ASCII; bodies are typically latin-1 or utf-8.
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return data.decode("latin-1")
    return data


def _strip_header(text: str) -> str:
    """Drop the OFX header block before the <OFX> root, if present."""
    idx = text.find("<OFX>")
    if idx == -1:
        idx = text.upper().find("<OFX>")
    return text[idx:] if idx != -1 else text


def _tag_value(block: str, tag: str) -> Optional[str]:
    """Return the first value for ``tag`` within ``block``, or None."""
    for found_tag, value in _TAG_RE.findall(block):
        if found_tag == tag:
            return value.strip()
    return None


def parse(data, *, default_currency: str = "USD") -> NormalizedStatement:
    """Parse OFX/QFX bytes/str into a NormalizedStatement."""
    text = _strip_header(_to_text(data))
    if "<OFX>" not in text and "<STMTTRN>" not in text:
        raise ParseError("input does not look like OFX/QFX")

    account_id = _tag_value(text, "ACCTID")
    currency = (_tag_value(text, "CURDEF") or default_currency).upper()

    txns: list[Transaction] = []
    for block in _iter_stmttrn_blocks(text):
        dt_raw = _tag_value(block, "DTPOSTED") or _tag_value(block, "DTUSER")
        amt_raw = _tag_value(block, "TRNAMT")
        if dt_raw is None or amt_raw is None:
            continue

        date = parse_ofx_date(dt_raw)
        amount = parse_money(amt_raw)

        name = _tag_value(block, "NAME") or ""
        memo = _tag_value(block, "MEMO") or ""
        description = " ".join(p for p in (name, memo) if p).strip()

        txns.append(
            Transaction.create(
                date=date,
                amount=amount,
                description=description,
                currency=currency,
                fitid=_tag_value(block, "FITID"),
                account_id=account_id,
                source_format="ofx",
                raw={"block": block.strip()},
            )
        )

    return NormalizedStatement(
        transactions=txns,
        account_id=account_id,
        currency=currency,
        source_format="ofx",
    )


def _iter_stmttrn_blocks(text: str):
    """Yield each <STMTTRN>...</STMTTRN> block as a string."""
    pos = 0
    upper = text.upper()
    while True:
        start = upper.find(_STMTTRN_OPEN, pos)
        if start == -1:
            return
        end = upper.find(_STMTTRN_CLOSE, start)
        if end == -1:
            return
        yield text[start + len(_STMTTRN_OPEN) : end]
        pos = end + len(_STMTTRN_CLOSE)
