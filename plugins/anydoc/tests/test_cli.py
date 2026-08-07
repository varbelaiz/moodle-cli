"""Tests for `moodle anydoc convert`."""

from __future__ import annotations

from pathlib import Path

from moodle_cli_anydoc.cli import app
from typer.testing import CliRunner

runner = CliRunner()


def test_convert_command_writes_markdown_and_reports_ok(tmp_path: Path) -> None:
    source = tmp_path / "grades.csv"
    source.write_text("a,b\n1,2\n", encoding="utf-8")

    result = runner.invoke(app, ["convert", str(source)])

    assert result.exit_code == 0
    assert (tmp_path / "grades.csv.md").exists()
    assert "ok" in result.stdout


def test_convert_command_exits_nonzero_on_a_failed_file(tmp_path: Path) -> None:
    result = runner.invoke(app, ["convert", str(tmp_path / "missing.docx")])

    assert result.exit_code == 1


def test_convert_command_keeps_going_after_one_failure(tmp_path: Path) -> None:
    """One bad file in a batch must not cost the rest their conversion."""
    good = tmp_path / "grades.csv"
    good.write_text("a,b\n1,2\n", encoding="utf-8")
    missing = tmp_path / "missing.docx"

    result = runner.invoke(app, ["convert", str(missing), str(good)])

    assert result.exit_code == 1
    assert (tmp_path / "grades.csv.md").exists()
