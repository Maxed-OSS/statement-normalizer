import json
from decimal import Decimal

from statement_normalizer import normalize_file
from statement_normalizer.cli import main
from statement_normalizer.normalize import detect_format, normalize_many


def test_detect_format(fixture_path):
    with open(fixture_path("sample.ofx"), "rb") as fh:
        assert detect_format(fh.read(), filename="sample.ofx") == "ofx"
    with open(fixture_path("bank_signed_amount.csv"), "rb") as fh:
        assert detect_format(fh.read(), filename="x.csv") == "csv"
    with open(fixture_path("statement.txt"), "rb") as fh:
        assert detect_format(fh.read(), filename="x.txt") == "text"


def test_detect_format_by_content(fixture_path):
    # No filename: rely on content sniffing.
    with open(fixture_path("sample.ofx"), "rb") as fh:
        assert detect_format(fh.read()) == "ofx"


def test_normalize_file_csv(fixture_path):
    stmt = normalize_file(fixture_path("bank_signed_amount.csv"))
    assert stmt.source_format == "csv"
    d = stmt.to_dict()
    assert d["transaction_count"] == len(stmt.transactions)
    # JSON-serializable
    json.dumps(d)


def test_cross_statement_merge_dedups_overlap(fixture_path):
    txns = normalize_many(
        [fixture_path("sample.ofx"), fixture_path("sample_overlap.ofx")]
    )
    fitids = [t.fitid for t in txns]
    # The shared FITID 20240112-0003 appears in both files but only once here.
    assert fitids.count("20240112-0003") == 1
    # Union of unique FITIDs across both files = 4.
    assert len(set(fitids)) == 4
    assert len(txns) == 4


def test_cli_single_file_json(fixture_path, capsys):
    rc = main([fixture_path("creditcard.csv"), "--pretty"])
    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["source_format"] == "csv"
    assert payload["transaction_count"] >= 1
    assert payload["source_file"].endswith("creditcard.csv")


def test_cli_merge(fixture_path, capsys):
    rc = main(
        [
            fixture_path("sample.ofx"),
            fixture_path("sample_overlap.ofx"),
            "--merge",
            "--pretty",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["merged"] is True
    assert payload["transaction_count"] == 4


def test_cli_missing_file_errors(capsys):
    rc = main(["/nonexistent/path/statement.csv"])
    assert rc == 1
    assert "error" in capsys.readouterr().err
