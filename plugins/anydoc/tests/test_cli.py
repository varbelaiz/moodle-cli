"""Tests for `moodle anydoc convert` and `moodle anydoc fetch`."""

from __future__ import annotations

from pathlib import Path

import pytest
from moodle_cli_anydoc import cli as cli_module
from moodle_cli_anydoc.cli import app
from moodle_cli_anydoc.convert import Converted
from typer.testing import CliRunner

runner = CliRunner()

# -- convert -----------------------------------------------------------------------


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


def test_convert_command_ocr_flag_reaches_convert_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, object] = {}

    def fake_convert_file(path: Path, *, ocr: bool = False) -> Converted:
        seen["ocr"] = ocr
        return Converted(path, "ok", path.with_name(f"{path.name}.md"))

    monkeypatch.setattr(cli_module, "convert_file", fake_convert_file)

    result = runner.invoke(app, ["convert", "--ocr", str(tmp_path / "scan.pdf")])

    assert result.exit_code == 0
    assert seen["ocr"] is True


# -- fetch -------------------------------------------------------------------------


def test_fetch_command_reports_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    converted = Converted(tmp_path / "grades.csv", "| 1 |", tmp_path / "grades.csv.md")
    monkeypatch.setattr(
        cli_module,
        "fetch_and_convert",
        lambda course, filename, section=None, ocr=False: converted,
    )

    result = runner.invoke(app, ["fetch", "IOS460", "grades.csv"])

    assert result.exit_code == 0
    assert "ok" in result.stdout


def test_fetch_command_reports_a_clean_error_on_no_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_not_found(
        course: str, filename: str, section: int | None = None, ocr: bool = False
    ) -> Converted:
        raise ValueError(f"{filename!r}: no such file in {course}")

    monkeypatch.setattr(cli_module, "fetch_and_convert", raise_not_found)

    result = runner.invoke(app, ["fetch", "IOS460", "missing.pdf"])

    assert result.exit_code == 1
    assert "Error" in result.output


def test_fetch_command_passes_the_section_option(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_fetch_and_convert(
        course: str, filename: str, section: int | None = None, ocr: bool = False
    ) -> Converted:
        seen["section"] = section
        return Converted(Path("a.csv"), "ok", Path("a.csv.md"))

    monkeypatch.setattr(cli_module, "fetch_and_convert", fake_fetch_and_convert)

    result = runner.invoke(app, ["fetch", "IOS460", "notes.csv", "--section", "2"])

    assert result.exit_code == 0
    assert seen["section"] == 2


def test_fetch_command_ocr_flag_reaches_fetch_and_convert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    def fake_fetch_and_convert(
        course: str, filename: str, section: int | None = None, ocr: bool = False
    ) -> Converted:
        seen["ocr"] = ocr
        return Converted(Path("a.pdf"), "ok", Path("a.pdf.md"))

    monkeypatch.setattr(cli_module, "fetch_and_convert", fake_fetch_and_convert)

    result = runner.invoke(app, ["fetch", "IOS460", "scan.pdf", "--ocr"])

    assert result.exit_code == 0
    assert seen["ocr"] is True
