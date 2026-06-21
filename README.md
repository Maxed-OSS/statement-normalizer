# statement-normalizer

[![CI](https://github.com/maxed-oss/statement-normalizer/actions/workflows/ci.yml/badge.svg)](https://github.com/maxed-oss/statement-normalizer/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

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

- Parses the statement shapes banks and cards actually export:
  - **CSV** — signed-amount or separate debit/credit columns, optional running
    balance, fuzzy header detection with a broad alias table covering the
    real-world headers from Chase, Bank of America, Wells Fargo, Amex, Capital
    One, Discover and many others.
  - **OFX / QFX** — both the SGML (OFX 1.x) and XML (OFX 2.x) export styles,
    using a small built-in tokenizer (no external OFX dependency).
  - **MT940** — the SWIFT bank-statement message format (`.sta` / `.940`),
    common for European business accounts.
  - **CAMT.053** — ISO 20022 `BankToCustomerStatement` XML, the modern standard
    replacing MT940. Parsed with the standard-library XML parser, namespace-agnostic.
  - **Text** — line-oriented statement text, e.g. the output of running a PDF
    through a text extractor like `pdftotext`.

### Format support matrix

| Format | Extensions | Direction source | Account id | Strong dedup key | Multi-currency |
|---|---|---|---|---|---|
| CSV (signed) | `.csv` | sign of `Amount` (or `--invert-amounts`) | – | content hash | per-row `Currency` col |
| CSV (debit/credit) | `.csv` | which column is populated | – | content hash | per-row `Currency` col |
| OFX / QFX | `.ofx` `.qfx` | signed `TRNAMT` | `ACCTID` | `FITID` | `CURDEF` |
| MT940 | `.sta` `.940` `.mt940` | `D` / `C` mark on `:61:` | `:25:` | content hash | `:60F:` currency |
| CAMT.053 | `.xml` (sniffed) | `CdtDbtInd` (`DBIT`/`CRDT`) | IBAN / `Othr` id | `AcctSvcrRef` | `Amt@Ccy` |
| Text / PDF-text | `.txt` | sign / column heuristic | – | content hash | `--currency` default |

All amounts are normalized to one sign convention (debits negative, credits
positive) regardless of how the source expressed direction.
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

# MT940 and CAMT.053 work the same way
statement-normalizer export.sta --stats
statement-normalizer --format camt053 statement.xml

# Merge overlapping monthly exports, de-duplicating across them
statement-normalizer jan.csv feb.csv --merge -o all.json

# Flat CSV instead of JSON
statement-normalizer statement.ofx --csv -o transactions.csv

# Print a summary (counts, totals, date range) to stderr while still emitting JSON
statement-normalizer statement.csv --stats

# Read from stdin ('-')
cat statement.csv | statement-normalizer --format csv -

# Issuers that report charges as positive / payments as negative (e.g. some
# credit-card exports) — flip the sign into the debit-negative convention
statement-normalizer amex.csv --invert-amounts

# Set a default currency when the source omits one
statement-normalizer eu_statement.csv --currency EUR
```

### CLI flags

| Flag | Effect |
|---|---|
| `--format {csv,ofx,text,mt940,camt053}` | force input format (default: auto-detect) |
| `--csv` | emit a flat transactions CSV instead of JSON |
| `--stats` | print a counts/totals/date-range summary to stderr |
| `--merge` | merge all inputs into one cross-statement-deduped list |
| `--no-dedup` | disable de-duplication |
| `--invert-amounts` | flip the sign of CSV single-`Amount`-column values |
| `--currency CCY` | default currency when the source omits one |
| `--pretty` | pretty-print JSON |
| `-o FILE` | write to a file instead of stdout |

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

## Examples

The [`examples/`](examples) directory ships synthetic statements in the shapes
real banks and cards export, plus a runnable tour:

```bash
python examples/demo.py
```

| File | Shape it demonstrates |
|---|---|
| `chase_checking.csv` | Chase `Details/Posting Date/Description/Amount/Type/Balance` |
| `bofa_checking.csv` | Bank of America `Date/Description/Amount/Running Bal.` |
| `wells_fargo_checking.csv` | Wells Fargo `Date/Amount/*/Payee/Memo` (blank Payee, text in Memo) |
| `amex_creditcard.csv` | Amex single `Amount` with charges positive (use `--invert-amounts`) |
| `capital_one_creditcard.csv` | Capital One split `Debit`/`Credit` columns |
| `discover_creditcard.csv` | Discover `Trans. Date/Amount/Category` (charges positive) |
| `sample.mt940` | SWIFT MT940 (`:25:`/`:60F:`/`:61:`/`:86:`) |
| `sample.camt053.xml` | ISO 20022 CAMT.053 (`<Ntry>` / `CdtDbtInd`) |
| `overlap_jan.csv`, `overlap_feb.csv` | two overlapping months for the dedup/merge demo |

Dedup/merge across overlapping months in one line:

```bash
statement-normalizer examples/overlap_jan.csv examples/overlap_feb.csv --merge --stats
# 12 raw rows across the two files -> 9 after the 3 overlapping rows collapse,
# while a legitimately-repeated same-merchant charge is preserved.
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
python examples/demo.py   # runnable tour over the synthetic examples
```

The test suite runs entirely over synthetic sample statements committed under
[`tests/fixtures/`](tests/fixtures) and [`examples/`](examples). No real account
data is used anywhere in this project; please keep it that way and only commit
synthetic fixtures.

CI runs the tests on Python 3.9–3.13 (plus a macOS/Windows spot-check) and
builds the sdist + wheel on every push and pull request.

## License

[Apache-2.0](LICENSE).
