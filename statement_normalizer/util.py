"""Shared deterministic parsing helpers (dates, money, headers)."""

from __future__ import annotations

import datetime as _dt
import re
from decimal import Decimal, InvalidOperation
from typing import Optional

# Date formats we attempt, in order. All unambiguous or US-conventional.
_DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%m/%d/%Y",
    "%m/%d/%y",
    "%m-%d-%Y",
    "%m-%d-%y",
    "%d-%b-%Y",
    "%d-%b-%y",
    "%b %d %Y",
    "%b %d, %Y",
    "%Y%m%d",
)

# OFX datetime: YYYYMMDD with optional HHMMSS and optional [tz] suffix.
_OFX_DT_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})")

_MONEY_CLEAN_RE = re.compile(r"[,$\s]")
_PAREN_RE = re.compile(r"^\((.*)\)$")


class ParseError(ValueError):
    """Raised when a value cannot be deterministically parsed."""


def parse_date(value: str) -> _dt.date:
    """Parse a date string using a fixed set of formats. Raises ParseError."""
    if value is None:
        raise ParseError("empty date")
    s = value.strip()
    if not s:
        raise ParseError("empty date")
    for fmt in _DATE_FORMATS:
        try:
            return _dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ParseError(f"unrecognized date format: {value!r}")


def parse_ofx_date(value: str) -> _dt.date:
    """Parse an OFX/QFX DTPOSTED-style datetime into a date."""
    if value is None:
        raise ParseError("empty OFX date")
    m = _OFX_DT_RE.match(value.strip())
    if not m:
        raise ParseError(f"unrecognized OFX date: {value!r}")
    year, month, day = (int(g) for g in m.groups())
    try:
        return _dt.date(year, month, day)
    except ValueError as exc:
        raise ParseError(f"invalid OFX date: {value!r}") from exc


def parse_money(value: str) -> Decimal:
    """Parse a money string into a Decimal.

    Handles ``$``, thousands separators, leading ``+``, trailing/leading ``-``,
    and accounting-style parentheses for negatives, e.g. ``(1,234.56)``.
    """
    if value is None:
        raise ParseError("empty amount")
    s = value.strip()
    if not s:
        raise ParseError("empty amount")

    negative = False
    paren = _PAREN_RE.match(s)
    if paren:
        negative = True
        s = paren.group(1)

    # Trailing sign, e.g. "100.00-"
    if s.endswith("-"):
        negative = True
        s = s[:-1]
    if s.endswith("+"):
        s = s[:-1]

    s = _MONEY_CLEAN_RE.sub("", s)

    if s.startswith("-"):
        negative = True
        s = s[1:]
    elif s.startswith("+"):
        s = s[1:]

    if not s:
        raise ParseError(f"unparseable amount: {value!r}")

    try:
        amount = Decimal(s)
    except InvalidOperation as exc:
        raise ParseError(f"unparseable amount: {value!r}") from exc

    return -amount if negative else amount


def normalize_header(name: str) -> str:
    """Normalize a column header for fuzzy matching (lower, alnum only)."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def first_match(headers: list[str], candidates: tuple[str, ...]) -> Optional[int]:
    """Return the index of the first header matching any candidate token."""
    norm = [normalize_header(h) for h in headers]
    for cand in candidates:
        if cand in norm:
            return norm.index(cand)
    return None


def all_matches(headers: list[str], candidates: tuple[str, ...]) -> list[int]:
    """Return header indices matching any candidate, in candidate-priority order.

    Useful when a logical field can live in more than one column and a per-row
    fallback is needed (e.g. a blank ``Payee`` with the text in ``Memo``).
    """
    norm = [normalize_header(h) for h in headers]
    out: list[int] = []
    for cand in candidates:
        if cand in norm:
            idx = norm.index(cand)
            if idx not in out:
                out.append(idx)
    return out
