"""CLI polish: --csv output, --stats summary, stdin, new-format detection."""

import io
import json

import pytest

from statement_normalizer import cli
from statement_normalizer.normalize import detect_format


def test_cli_csv_output(fixture_path, capsys):
    rc = cli.main([fixture_path("bank_signed_amount.csv"), "--csv"])
    assert rc == 0
    out = capsys.readouterr().out
    lines = out.strip().splitlines()
    assert lines[0].startswith("date,amount,description,txn_type")
    # 6 data rows (the zero-amount opening adjustment is dropped) + header.
    assert len(lines) == 7
    assert any("COFFEE ROASTERS #221" in ln for ln in lines)


def test_cli_stats_to_stderr(fixture_path, capsys):
    rc = cli.main([fixture_path("bank_signed_amount.csv"), "--stats"])
    assert rc == 0
    err = capsys.readouterr().err
    assert "summary:" in err
    assert "transactions :" in err
    assert "date range" in err


def test_cli_stdin(fixture_path, monkeypatch, capsys):
    data = open(fixture_path("creditcard.csv"), "rb").read()

    class _Stdin:
        buffer = io.BytesIO(data)

    monkeypatch.setattr("sys.stdin", _Stdin())
    rc = cli.main(["--format", "csv", "-"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["source_format"] == "csv"
    assert payload["transaction_count"] >= 1


def test_cli_merge_csv(fixture_path, capsys):
    rc = cli.main(
        [
            fixture_path("overlap_jan.csv"),
            fixture_path("overlap_feb.csv"),
            "--merge",
            "--csv",
        ]
    )
    assert rc == 0
    lines = capsys.readouterr().out.strip().splitlines()
    # 9 merged txns + header (3 overlapping rows collapsed).
    assert len(lines) == 10


def test_detect_mt940_and_camt(fixture_path):
    with open(fixture_path("sample.mt940"), "rb") as fh:
        assert detect_format(fh.read(), filename="sample.mt940") == "mt940"
    with open(fixture_path("sample.camt053.xml"), "rb") as fh:
        # Content-sniffed (extension is .xml, not a format hint).
        assert detect_format(fh.read()) == "camt053"


def test_cli_missing_file_errors(capsys):
    rc = cli.main(["does_not_exist.csv"])
    assert rc == 1
    assert "error:" in capsys.readouterr().err
