"""CAMT.052 (ISO 20022 ``BankToCustomerAccountReport``) parser.

CAMT.052 is the ISO 20022 intra-day / interim account report. Banks send it
during the day to report activity before the end-of-day CAMT.053 statement is
cut. Its entry shape is identical to CAMT.053: a report (``<Rpt>``) contains a
sequence of entries (``<Ntry>``), each with an amount, a credit/debit indicator
(``<CdtDbtInd>``), a booking date, and remittance information.

Because the two messages share an entry model, this parser reuses the CAMT.053
entry logic and only changes the top-level container element (``<Rpt>`` instead
of ``<Stmt>``). It uses the standard library's XML parser and is
namespace-agnostic, so no external ISO-20022 dependency is required.

Sign convention: ``DBIT`` -> negative, ``CRDT`` -> positive.
"""

from __future__ import annotations

from ..schema import NormalizedStatement
from ..util import ParseError
from .camt053_parser import looks_like_camt052, parse_camt
from .camt053_parser import _to_text  # noqa: F401  (re-exported for symmetry)


def parse(data, *, default_currency: str = "USD") -> NormalizedStatement:
    """Parse CAMT.052 XML bytes/str into a NormalizedStatement."""
    if not looks_like_camt052(_to_text(data)):
        raise ParseError("input does not look like CAMT.052")
    return parse_camt(
        data,
        container_tags=("Rpt",),
        source_format="camt052",
        default_currency=default_currency,
        label="CAMT.052",
    )
