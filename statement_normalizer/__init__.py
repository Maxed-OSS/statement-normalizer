"""statement-normalizer: deterministic, rule-based bank & credit-card statement parsing.

Parses CSV, OFX/QFX, and simple text-table statements into a normalized
Transaction schema. No machine learning, no network calls, fully deterministic.
"""

from .schema import Transaction, NormalizedStatement
from .normalize import normalize_file, normalize_bytes
from .dedup import dedup_transactions

__version__ = "0.1.0"

__all__ = [
    "Transaction",
    "NormalizedStatement",
    "normalize_file",
    "normalize_bytes",
    "dedup_transactions",
    "__version__",
]
