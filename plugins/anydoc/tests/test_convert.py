"""Tests for local markdown conversion.

Runs against the real anydoc library rather than a mock: conversion is a pure, fast,
local function, so there is nothing a mock would buy here that the real thing does not
already give for free.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from moodle_cli_anydoc import convert as convert_module
from moodle_cli_anydoc.convert import ConversionError, convert_file


def test_convert_file_writes_markdown_alongside_the_source(tmp_path: Path) -> None:
    source = tmp_path / "grades.csv"
    source.write_text("name,grade\nAna,9\nLuis,7\n", encoding="utf-8")

    result = convert_file(source)

    assert result.markdown_path == tmp_path / "grades.csv.md"
    assert result.markdown_path.read_text(encoding="utf-8") == result.markdown
    assert "Ana" in result.markdown
    assert "Luis" in result.markdown


def test_convert_file_appends_rather_than_replaces_the_suffix(tmp_path: Path) -> None:
    """Two files sharing a stem in different formats must not collide on output."""
    csv = tmp_path / "Programa.csv"
    csv.write_text("a,b\n1,2\n", encoding="utf-8")

    result = convert_file(csv)

    assert result.markdown_path.name == "Programa.csv.md"
    assert result.markdown_path != tmp_path / "Programa.pdf.md"


def test_convert_file_raises_on_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConversionError):
        convert_file(tmp_path / "missing.docx")


def test_an_unwritable_destination_is_a_conversion_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The write is as much a way to fail as the conversion, so it fails the same way.

    Escaping as a bare OSError, it would abort a whole batch on one bad destination and
    reach the user as a traceback, since the CLI only contains ConversionError.
    """
    source = tmp_path / "grades.csv"
    source.write_text("name,grade\nAna,9\n", encoding="utf-8")

    def refuse(*args: object, **kwargs: object) -> None:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, "write_text", refuse)

    with pytest.raises(ConversionError, match="could not write the markdown"):
        convert_file(source)


def test_convert_file_raises_on_an_unconvertible_file(tmp_path: Path) -> None:
    """Garbage bytes under a real extension: anydoc finds nothing meaningful in it."""
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"this is not a pdf")

    with pytest.raises(ConversionError):
        convert_file(broken)


# -- ocr=True ------------------------------------------------------------------------


def test_convert_file_ocr_without_a_key_fails_without_touching_the_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "scan.pdf"
    source.write_bytes(b"%PDF-fake")
    monkeypatch.setattr(convert_module, "resolve_firecrawl_key", lambda: None)

    def fail_if_called(source: Path, api_key: str) -> str:
        raise AssertionError("convert_hosted must not run without a key")

    monkeypatch.setattr(convert_module, "convert_hosted", fail_if_called)

    with pytest.raises(ConversionError, match="FIRECRAWL_KEY"):
        convert_file(source, ocr=True)


def test_convert_file_ocr_delegates_to_the_hosted_converter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "scan.pdf"
    source.write_bytes(b"%PDF-fake")
    monkeypatch.setattr(convert_module, "resolve_firecrawl_key", lambda: "fc-test-key")
    monkeypatch.setattr(
        convert_module, "convert_hosted", lambda source, api_key: "# Recovered by OCR"
    )

    result = convert_file(source, ocr=True)

    assert result.markdown == "# Recovered by OCR"
    assert result.markdown_path.read_text(encoding="utf-8") == "# Recovered by OCR"


def test_convert_file_ocr_wraps_a_hosted_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from moodle_cli_anydoc.hosted import HostedError

    source = tmp_path / "scan.pdf"
    source.write_bytes(b"%PDF-fake")
    monkeypatch.setattr(convert_module, "resolve_firecrawl_key", lambda: "fc-test-key")

    def raise_hosted_error(source: Path, api_key: str) -> str:
        raise HostedError("rate limit exceeded")

    monkeypatch.setattr(convert_module, "convert_hosted", raise_hosted_error)

    with pytest.raises(ConversionError, match="rate limit exceeded"):
        convert_file(source, ocr=True)
