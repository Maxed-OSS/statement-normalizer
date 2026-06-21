# statement-normalizer

Turn messy bank and credit-card statements into clean, normalized transaction
JSON. Deterministic, rule-based, dependency-free, and easy to audit.

No machine learning. No network calls. No surprises. Given the same input you
get the same output, every time, which is exactly what you want when the data
feeds bookkeeping, reconciliation, or any financial workflow.

## Why

Every bank exports statements differently: some give you a single signed
`Amount` column, others split `Debit` / `Credit`, some wrap negatives in
parentheses, some hand you OFX/QFX, some only give you a PDF. Downstream tools
all want the same thing: a tidy list of transactions with a consistent sign
convention, parsed dates, and proper decimal amounts.

`statement-normalizer` is the small, boring, well-tested glue layer that does
exactly that and nothing more. It is meant to be a building block you can drop
into an import pipeline, not a full accounting system.

## What it does

- Parses three common statement shapes:
  - **CSV** — signed-amount or separate debit/credit columns, optional running
    balance, fuzzy header detection so it works across many banks.
  - **OFX / QFX** — both the SGML (OFX 1.x) and XML (OFX 2.x) export styles,
    using a small built-in tokenizer (no external OFX dependency).
  - **Text** — line-oriented statement text, e.g. the output of running a PDF
    through a text extractor like `pdftotext`.
- Emits a single normalized [`Transaction`](statement_normalizer/schema.py)
  schema with a consistent sign convention (debits negative, credits positive),
  parsed `date`, `Decimal` `amount`, derived `txn_type`, optional `balance`,
  `fitid`, `account_id`, and currency.
- De-duplicates transactions with deterministic heuristics:
  - Bank-assigned `FITID` (from OFX) is the authoritative key when present.
  - Otherwise a content hash over (date, signed amount, currency, canonical
    description), while preserving legitimately-repeated same-day charges.
- Merges multiple statements (e.g. overlapping monthly exports) into one
  de-duplicated list.
- Ships a CLI and a small Python API.

### Out of scope (on purpose)

- **Binary PDF decoding.** Pipe your PDF through a text extractor first, then
  feed the text in. This keeps the library dependency-free and deterministic.
- **Transaction categorization / ML.** This normalizes; it does not classify.

## Install

```bash
pip install statement-normalizer
```

Or from a checkout:

```bash
pip install -e .
```

Python 3.9+. No runtime dependencies.

## Usage — CLI

```bash
# Normalize a single file (format auto-detected by extension/content)
statement-normalizer statement.csv --pretty

# Force a format
statement-normalizer --format ofx export.qfx

# Merge overlapping monthly exports, de-duplicating across them
statement-normalizer jan.csv feb.csv --merge -o all.json

# Set a default currency when the source omits one
statement-normalizer eu_statement.csv --currency EUR
```

## Usage — Python

```python
from statement_normalizer import normalize_file

statement = normalize_file("statement.csv")
print(statement.account_id, statement.currency)

for txn in statement.transactions:
    print(txn.date, txn.amount, txn.txn_type.value, txn.description)

# JSON-serializable dict
import json
print(json.dumps(statement.to_dict(), indent=2))
```

Merging multiple files with cross-statement dedup:

```python
from statement_normalizer.normalize import normalize_many

txns = normalize_many(["jan.ofx", "feb.ofx"])
```

## Example output

Input CSV:

```csv
Transaction Date,Description,Amount
2024-02-01,GAS STATION 4471,(45.20)
2024-02-05,PAYMENT - THANK YOU,250.00
```

Output JSON (abridged):

```json
{
  "account_id": null,
  "currency": "USD",
  "source_format": "csv",
  "transaction_count": 2,
  "transactions": [
    {
      "date": "2024-02-01",
      "amount": "-45.20",
      "description": "GAS STATION 4471",
      "txn_type": "debit",
      "currency": "USD",
      "balance": null,
      "fitid": null,
      "account_id": null,
      "source_format": "csv"
    },
    {
      "date": "2024-02-05",
      "amount": "250.00",
      "description": "PAYMENT - THANK YOU",
      "txn_type": "credit",
      "currency": "USD",
      "balance": null,
      "fitid": null,
      "account_id": null,
      "source_format": "csv"
    }
  ]
}
```

## Sign convention

`amount` is always signed: **negative = money out (debit)**, **positive = money
in (credit)**. `txn_type` is derived from the sign for convenience. Parsers
normalize to this convention regardless of how the source expressed direction
(separate debit columns, parentheses, trailing minus, etc.).

## Development

```bash
pip install -e ".[dev]"
pytest
```

The test suite runs entirely over synthetic sample statements committed under
[`tests/fixtures/`](tests/fixtures). No real account data is used anywhere in
this project; please keep it that way and only commit synthetic fixtures.

## License

[Apache-2.0](LICENSE).
