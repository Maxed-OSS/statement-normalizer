"""Format-specific parsers. Each exposes ``parse(data: str|bytes) -> NormalizedStatement``."""

from . import (
    camt052_parser,
    camt053_parser,
    csv_parser,
    mt940_parser,
    ofx_parser,
    qif_parser,
    text_parser,
)

__all__ = [
    "csv_parser",
    "ofx_parser",
    "text_parser",
    "mt940_parser",
    "camt053_parser",
    "camt052_parser",
    "qif_parser",
]
