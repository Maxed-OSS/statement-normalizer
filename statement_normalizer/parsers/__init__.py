"""Format-specific parsers. Each exposes ``parse(data: str|bytes) -> NormalizedStatement``."""

from . import csv_parser, ofx_parser, text_parser

__all__ = ["csv_parser", "ofx_parser", "text_parser"]
