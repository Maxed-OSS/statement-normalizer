"""Top-level normalization API: detect format, parse, optionally dedup."""

from __future__ import annotations

import os
from typing import Optional

from .dedup import dedup_transactions, source_multiplicity
from .parsers import (
    camt052_parser,
    camt053_parser,
    csv_parser,
    mt940_parser,
    ofx_parser,
    qif_parser,
    text_parser,
)
from .schema import NormalizedStatement, Transaction
from .util import ParseError

# Format names accepted by ``format=`` overrides.
FORMATS = ("csv", "ofx", "text", "mt940", "camt053", "camt052", "qif")

# Extensions that map to a single format. ``.xml`` is intentionally absent: it
# falls through to content sniffing so CAMT.053 and CAMT.052 (both XML) can be
# told apart by their container element.
_EXT_TO_FORMAT = {
    "ofx": "ofx",
    "qfx": "ofx",
    "csv": "csv",
    "sta": "mt940",
    "mt940": "mt940",
    "940": "mt940",
    "qif": "qif",
    "txt": "text",
    "text": "text",
}


def detect_format(data, *, filename: Optional[str] = None) -> str:
    """Best-effort deterministic format detection.

    Uses the file extension first (most reliable), then content sniffing.
    """
    if filename:
        ext = os.path.splitext(filename)[1].lower().lstrip(".")
        if ext in _EXT_TO_FORMAT:
            return _EXT_TO_FORMAT[ext]
        # .xml falls through to content sniffing (CAMT.053 vs CAMT.052).

    text = data.decode("utf-8", errors="replace") if isinstance(data, bytes) else data
    stripped = text.lstrip()
    head = stripped[:2048].upper()

    if "<OFX>" in head or "OFXHEADER" in head or "<STMTTRN>" in head:
        return "ofx"
    # CAMT.052 (intra-day report) must be checked before CAMT.053 because some
    # bundles carry both namespaces; the container element is the tiebreaker.
    if "BKTOCSTMRACCTRPT" in head or "CAMT.052" in head:
        return "camt052"
    if "BKTOCSTMRSTMT" in head or "CAMT.053" in head:
        return "camt053"
    # QIF starts with a !Type:/!Account header line.
    if head.startswith("!TYPE:") or head.startswith("!ACCOUNT"):
        return "qif"
    # MT940: colon-tag fields (:20: / :25: / :61:).
    if mt940_parser.looks_like_mt940(text):
        return "mt940"
    # CSV if the first line has commas and looks like a header row.
    first_line = text.splitlines()[0] if text.splitlines() else ""
    if "," in first_line and not first_line.lstrip().startswith("<"):
        return "csv"
    return "text"


def _parse(
    data, fmt: str, *, default_currency: str, invert_amount: bool = False
) -> NormalizedStatement:
    if fmt == "csv":
        return csv_parser.parse(
            data, default_currency=default_currency, invert_amount=invert_amount
        )
    if fmt == "ofx":
        return ofx_parser.parse(data, default_currency=default_currency)
    if fmt == "text":
        return text_parser.parse(data, default_currency=default_currency)
    if fmt == "mt940":
        return mt940_parser.parse(data, default_currency=default_currency)
    if fmt == "camt053":
        return camt053_parser.parse(data, default_currency=default_currency)
    if fmt == "camt052":
        return camt052_parser.parse(data, default_currency=default_currency)
    if fmt == "qif":
        return qif_parser.parse(data, default_currency=default_currency)
    raise ParseError(f"unknown format: {fmt!r}")


def normalize_bytes(
    data,
    *,
    fmt: Optional[str] = None,
    filename: Optional[str] = None,
    default_currency: str = "USD",
    dedup: bool = True,
    invert_amount: bool = False,
) -> NormalizedStatement:
    """Normalize a single statement's bytes/str into a NormalizedStatement."""
    resolved = fmt or detect_format(data, filename=filename)
    statement = _parse(
        data, resolved, default_currency=default_currency, invert_amount=invert_amount
    )
    if dedup:
        mult = source_multiplicity(statement.transactions)
        statement.transactions = dedup_transactions(
            statement.transactions, per_source_multiplicity=mult
        )
    return statement


def normalize_file(
    path: str,
    *,
    fmt: Optional[str] = None,
    default_currency: str = "USD",
    dedup: bool = True,
    invert_amount: bool = False,
) -> NormalizedStatement:
    """Normalize a statement file on disk."""
    with open(path, "rb") as fh:
        data = fh.read()
    return normalize_bytes(
        data,
        fmt=fmt,
        filename=path,
        default_currency=default_currency,
        dedup=dedup,
        invert_amount=invert_amount,
    )


def normalize_many(
    sources,
    *,
    fmt: Optional[str] = None,
    default_currency: str = "USD",
    invert_amount: bool = False,
) -> list[Transaction]:
    """Normalize and merge multiple statements, de-duplicating across them.

    ``sources`` may be either a list of file paths (``["jan.ofx", "feb.ofx"]``)
    or a list of ``(data, filename)`` tuples where ``data`` is bytes/str already
    read into memory and ``filename`` (or ``None``) drives format detection. The
    tuple form lets callers feed stdin or in-memory buffers.

    Per-statement multiplicity is computed first, then the max across all source
    statements is used so legitimate repeated charges survive while true
    cross-statement overlaps collapse.
    """
    all_txns: list[Transaction] = []
    max_mult: dict[str, int] = {}
    for source in sources:
        if isinstance(source, tuple):
            data, filename = source
            statement = normalize_bytes(
                data,
                fmt=fmt,
                filename=filename,
                default_currency=default_currency,
                dedup=False,
                invert_amount=invert_amount,
            )
        else:
            statement = normalize_file(
                source,
                fmt=fmt,
                default_currency=default_currency,
                dedup=False,
                invert_amount=invert_amount,
            )
        all_txns.extend(statement.transactions)
        for chash, count in source_multiplicity(statement.transactions).items():
            if count > max_mult.get(chash, 0):
                max_mult[chash] = count

    return dedup_transactions(all_txns, per_source_multiplicity=max_mult)
