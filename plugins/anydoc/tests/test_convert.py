"""Tests for local markdown conversion.

Runs against the real anydoc library rather than a mock: conversion is a pure, fast,
local function, so there is nothing a mock would buy here that the real thing does not
already give for free.
"""

from __future__ import annotations

from pathlib import Path

import pytest
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


def test_convert_file_raises_on_an_unconvertible_file(tmp_path: Path) -> None:
    """Garbage bytes under a real extension: anydoc finds nothing meaningful in it."""
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"this is not a pdf")

    with pytest.raises(ConversionError):
        convert_file(broken)
