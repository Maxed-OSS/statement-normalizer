"""Top-level normalization API: detect format, parse, optionally dedup."""

from __future__ import annotations

import os
from typing import Optional

from .dedup import dedup_transactions, source_multiplicity
from .parsers import csv_parser, ofx_parser, text_parser
from .schema import NormalizedStatement, Transaction
from .util import ParseError

# Format names accepted by ``format=`` overrides.
FORMATS = ("csv", "ofx", "text")


def detect_format(data, *, filename: Optional[str] = None) -> str:
    """Best-effort deterministic format detection.

    Uses the file extension first (most reliable), then content sniffing.
    """
    if filename:
        ext = os.path.splitext(filename)[1].lower().lstrip(".")
        if ext in ("ofx", "qfx"):
            return "ofx"
        if ext == "csv":
            return "csv"
        if ext in ("txt", "text"):
            return "text"

    text = data.decode("utf-8", errors="replace") if isinstance(data, bytes) else data
    head = text.lstrip()[:512].upper()

    if "<OFX>" in head or "OFXHEADER" in head or "<STMTTRN>" in head:
        return "ofx"
    # CSV if the first line has commas and looks like a header row.
    first_line = text.splitlines()[0] if text.splitlines() else ""
    if "," in first_line and not first_line.lstrip().startswith("<"):
        return "csv"
    return "text"


def _parse(data, fmt: str, *, default_currency: str) -> NormalizedStatement:
    if fmt == "csv":
        return csv_parser.parse(data, default_currency=default_currency)
    if fmt == "ofx":
        return ofx_parser.parse(data, default_currency=default_currency)
    if fmt == "text":
        return text_parser.parse(data, default_currency=default_currency)
    raise ParseError(f"unknown format: {fmt!r}")


def normalize_bytes(
    data,
    *,
    fmt: Optional[str] = None,
    filename: Optional[str] = None,
    default_currency: str = "USD",
    dedup: bool = True,
) -> NormalizedStatement:
    """Normalize a single statement's bytes/str into a NormalizedStatement."""
    resolved = fmt or detect_format(data, filename=filename)
    statement = _parse(data, resolved, default_currency=default_currency)
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
    )


def normalize_many(
    paths: list[str],
    *,
    default_currency: str = "USD",
) -> list[Transaction]:
    """Normalize and merge multiple statement files, de-duplicating across them.

    Per-statement multiplicity is computed first, then the max across all source
    statements is used so legitimate repeated charges survive while true
    cross-statement overlaps collapse.
    """
    all_txns: list[Transaction] = []
    max_mult: dict[str, int] = {}
    for path in paths:
        statement = normalize_file(path, default_currency=default_currency, dedup=False)
        all_txns.extend(statement.transactions)
        for chash, count in source_multiplicity(statement.transactions).items():
            if count > max_mult.get(chash, 0):
                max_mult[chash] = count

    return dedup_transactions(all_txns, per_source_multiplicity=max_mult)
