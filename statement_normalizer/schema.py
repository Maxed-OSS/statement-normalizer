"""Normalized transaction schema.

A ``Transaction`` is the canonical, format-independent representation of a single
line item on a bank or credit-card statement. All parsers emit these.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import re
from dataclasses import dataclass, field, asdict
from decimal import Decimal
from enum import Enum
from typing import Any, Optional


class TxnType(str, Enum):
    """Sign-normalized direction of a transaction.

    ``DEBIT`` reduces the account balance (money out), ``CREDIT`` increases it
    (money in). Sign on ``amount`` is the source of truth; ``txn_type`` is a
    convenience derived from it.
    """

    DEBIT = "debit"
    CREDIT = "credit"


_WS_RE = re.compile(r"\s+")


def _canon_description(raw: str) -> str:
    """Collapse whitespace and uppercase a description for matching/hashing."""
    return _WS_RE.sub(" ", (raw or "").strip()).upper()


def _q2(value: Decimal) -> Decimal:
    """Quantize to 2 decimal places (cent precision)."""
    return value.quantize(Decimal("0.01"))


@dataclass(frozen=True)
class Transaction:
    """A single normalized statement line.

    Attributes
    ----------
    date:
        Posting/transaction date (no time component).
    amount:
        Signed amount. Negative = money out (debit), positive = money in
        (credit). Always quantized to cents.
    description:
        Raw merchant/payee description as it appeared on the statement.
    txn_type:
        Derived debit/credit direction.
    currency:
        ISO-4217 currency code (defaults to ``USD``).
    balance:
        Running account balance after this transaction, if the source provided
        it. ``None`` otherwise.
    fitid:
        Financial-institution transaction id (from OFX/QFX), if present. Used as
        a strong dedup key when available.
    account_id:
        Source account identifier (account number / OFX acctid), if present.
    source_format:
        Which parser produced the row (``csv`` / ``ofx`` / ``text``).
    raw:
        Original parsed field map, for debugging/traceability.
    """

    date: _dt.date
    amount: Decimal
    description: str
    txn_type: TxnType
    currency: str = "USD"
    balance: Optional[Decimal] = None
    fitid: Optional[str] = None
    account_id: Optional[str] = None
    source_format: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict, compare=False, hash=False)

    @classmethod
    def create(
        cls,
        *,
        date: _dt.date,
        amount: Decimal,
        description: str,
        currency: str = "USD",
        balance: Optional[Decimal] = None,
        fitid: Optional[str] = None,
        account_id: Optional[str] = None,
        source_format: Optional[str] = None,
        raw: Optional[dict[str, Any]] = None,
    ) -> "Transaction":
        """Build a Transaction with derived/normalized fields filled in."""
        amount = _q2(Decimal(amount))
        txn_type = TxnType.CREDIT if amount > 0 else TxnType.DEBIT
        return cls(
            date=date,
            amount=amount,
            description=(description or "").strip(),
            txn_type=txn_type,
            currency=(currency or "USD").upper(),
            balance=_q2(Decimal(balance)) if balance is not None else None,
            fitid=fitid.strip() if fitid else None,
            account_id=account_id.strip() if account_id else None,
            source_format=source_format,
            raw=raw or {},
        )

    @property
    def canonical_description(self) -> str:
        """Whitespace-collapsed, uppercased description for matching."""
        return _canon_description(self.description)

    def content_hash(self) -> str:
        """Stable hash over the identity-bearing fields.

        Two rows with the same date, signed amount, currency and canonical
        description are considered the same transaction when no FITID is
        available. Used by the dedup heuristics.
        """
        key = "|".join(
            [
                self.date.isoformat(),
                f"{self.amount:.2f}",
                self.currency,
                self.canonical_description,
            ]
        )
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable dict (Decimals -> str, dates -> ISO, enum -> value)."""
        return {
            "date": self.date.isoformat(),
            "amount": f"{self.amount:.2f}",
            "description": self.description,
            "txn_type": self.txn_type.value,
            "currency": self.currency,
            "balance": (f"{self.balance:.2f}" if self.balance is not None else None),
            "fitid": self.fitid,
            "account_id": self.account_id,
            "source_format": self.source_format,
        }


@dataclass
class NormalizedStatement:
    """A parsed statement: account metadata plus normalized transactions."""

    transactions: list[Transaction] = field(default_factory=list)
    account_id: Optional[str] = None
    currency: str = "USD"
    source_format: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "currency": self.currency,
            "source_format": self.source_format,
            "transaction_count": len(self.transactions),
            "transactions": [t.to_dict() for t in self.transactions],
        }
