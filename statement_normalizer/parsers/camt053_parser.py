"""CAMT.053 (ISO 20022 ``BankToCustomerStatement``) parser.

CAMT.053 is the modern XML bank-statement standard that is replacing MT940.
A statement (``<Stmt>``) contains a sequence of entries (``<Ntry>``); each entry
carries an amount, a credit/debit indicator (``<CdtDbtInd>`` = ``CRDT``/``DBIT``),
a booking date, and free-text / structured remittance information.

We parse it with the standard library's ``xml.etree.ElementTree`` and ignore XML
namespaces (CAMT documents are namespaced, e.g.
``urn:iso:std:iso:20022:tech:xsd:camt.053.001.02``) by matching on the local tag
name. No external ISO-20022 dependency is required.

Sign convention: ``DBIT`` -> negative, ``CRDT`` -> positive. Amounts are decimal
with a dot separator and an ``Ccy`` attribute we read as the currency.
"""

from __future__ import annotations

import datetime as _dt
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation
from typing import Iterable, Optional

from ..schema import NormalizedStatement, Transaction
from ..util import ParseError


def _to_text(data) -> str:
    if isinstance(data, bytes):
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return data.decode("latin-1")
    return data


def _local(tag: str) -> str:
    """Strip any ``{namespace}`` prefix from an ElementTree tag."""
    return tag.rsplit("}", 1)[-1]


def _find(elem, *names) -> Optional[ET.Element]:
    """Depth-first find a descendant whose local tag matches any of ``names``."""
    wanted = set(names)
    for child in elem.iter():
        if _local(child.tag) in wanted:
            return child
    return None


def _findall_local(elem, name) -> Iterable[ET.Element]:
    for child in elem.iter():
        if _local(child.tag) == name:
            yield child


def looks_like_camt053(text: str) -> bool:
    head = text[:2048]
    return ("BkToCstmrStmt" in head or "camt.053" in head) and "<" in head


def looks_like_camt052(text: str) -> bool:
    head = text[:2048]
    return ("BkToCstmrAcctRpt" in head or "camt.052" in head) and "<" in head


def _parse_date(elem) -> Optional[_dt.date]:
    """Read a date from a ``<BookgDt>``/``<ValDt>`` block (``<Dt>`` or ``<DtTm>``)."""
    if elem is None:
        return None
    node = _find(elem, "Dt", "DtTm")
    if node is None or not (node.text or "").strip():
        return None
    raw = node.text.strip()
    # Date or datetime; take the date portion before any 'T'.
    raw = raw.split("T", 1)[0]
    try:
        return _dt.date.fromisoformat(raw)
    except ValueError:
        return None


def _entry_description(ntry: ET.Element) -> str:
    """Best-effort human description from remittance / related-party info."""
    parts: list[str] = []
    # Unstructured remittance info: <RmtInf><Ustrd>...</Ustrd>
    for ustrd in _findall_local(ntry, "Ustrd"):
        if ustrd.text and ustrd.text.strip():
            parts.append(ustrd.text.strip())
    if not parts:
        # Fall back to counterparty name (creditor/debtor <Nm>).
        rltd = _find(ntry, "RltdPties")
        if rltd is not None:
            nm = _find(rltd, "Nm")
            if nm is not None and nm.text and nm.text.strip():
                parts.append(nm.text.strip())
    if not parts:
        # Last resort: additional entry info.
        addtl = _find(ntry, "AddtlNtryInf")
        if addtl is not None and addtl.text and addtl.text.strip():
            parts.append(addtl.text.strip())
    return " ".join(parts).strip()


def parse_camt(
    data,
    *,
    container_tags,
    source_format: str,
    default_currency: str = "USD",
    label: str = "CAMT",
) -> NormalizedStatement:
    """Parse an ISO 20022 CAMT entry container into a NormalizedStatement.

    CAMT.053 (``BankToCustomerStatement``) and CAMT.052
    (``BankToCustomerAccountReport``) share an identical entry shape; only the
    top-level container element differs (``<Stmt>`` vs ``<Rpt>``). This helper
    parses either by accepting the candidate ``container_tags`` to look for.
    """
    text = _to_text(data)

    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ParseError(f"invalid {label} XML: {exc}") from exc

    stmt = _find(root, *container_tags)
    if stmt is None:
        wanted = "/".join(f"<{t}>" for t in container_tags)
        raise ParseError(f"{label} has no {wanted} element")

    # Account id: <Acct><Id><IBAN> or <Othr><Id>.
    account_id: Optional[str] = None
    acct = _find(stmt, "Acct")
    if acct is not None:
        iban = _find(acct, "IBAN")
        if iban is not None and iban.text:
            account_id = iban.text.strip()
        else:
            othr = _find(acct, "Othr")
            if othr is not None:
                idn = _find(othr, "Id")
                if idn is not None and idn.text:
                    account_id = idn.text.strip()

    statement_ccy = default_currency
    txns: list[Transaction] = []

    for ntry in _findall_local(stmt, "Ntry"):
        amt_el = _find(ntry, "Amt")
        ind_el = _find(ntry, "CdtDbtInd")
        if amt_el is None or ind_el is None or not (amt_el.text or "").strip():
            continue

        try:
            magnitude = Decimal(amt_el.text.strip())
        except InvalidOperation:
            continue

        ccy = (amt_el.get("Ccy") or statement_ccy or default_currency).upper()
        if statement_ccy == default_currency and amt_el.get("Ccy"):
            statement_ccy = ccy

        indicator = (ind_el.text or "").strip().upper()
        negative = indicator == "DBIT"
        amount = -magnitude if negative else magnitude

        # Booking date preferred, else value date.
        date = _parse_date(_find(ntry, "BookgDt")) or _parse_date(
            _find(ntry, "ValDt")
        )
        if date is None:
            continue

        # FITID-equivalent: account-servicer reference uniquely ids the entry.
        acct_svcr = _find(ntry, "AcctSvcrRef")
        fitid = (
            acct_svcr.text.strip()
            if acct_svcr is not None and acct_svcr.text and acct_svcr.text.strip()
            else None
        )

        txns.append(
            Transaction.create(
                date=date,
                amount=amount,
                description=_entry_description(ntry),
                currency=ccy,
                fitid=fitid,
                account_id=account_id,
                source_format=source_format,
                raw={"cdtdbtind": indicator},
            )
        )

    return NormalizedStatement(
        transactions=txns,
        account_id=account_id,
        currency=statement_ccy,
        source_format=source_format,
    )


def parse(data, *, default_currency: str = "USD") -> NormalizedStatement:
    """Parse CAMT.053 XML bytes/str into a NormalizedStatement."""
    if not looks_like_camt053(_to_text(data)):
        raise ParseError("input does not look like CAMT.053")
    return parse_camt(
        data,
        container_tags=("Stmt",),
        source_format="camt053",
        default_currency=default_currency,
        label="CAMT.053",
    )
