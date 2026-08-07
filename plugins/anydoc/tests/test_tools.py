"""Tests for the `anydoc_convert` MCP tool."""

from __future__ import annotations

from pathlib import Path

import pytest
from moodle_cli_anydoc import tools as tools_module
from moodle_cli_anydoc.convert import ConversionError, Converted
from moodle_cli_anydoc.tools import INLINE_LIMIT, convert


def test_convert_returns_markdown_and_path(tmp_path: Path) -> None:
    source = tmp_path / "grades.csv"
    source.write_text("a,b\n1,2\n", encoding="utf-8")

    payload = convert(str(source))

    assert payload["path"] == str(source)
    assert payload["markdown_path"] == str(tmp_path / "grades.csv.md")
    assert payload["truncated"] is False
    assert "1" in payload["markdown"]


def test_convert_truncates_long_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "big.csv"
    source.write_text("a\n", encoding="utf-8")
    long_markdown = "x" * (INLINE_LIMIT + 500)

    def fake_convert_file(path: Path) -> Converted:
        target = path.with_name(f"{path.name}.md")
        target.write_text(long_markdown, encoding="utf-8")
        return Converted(path, long_markdown, target)

    monkeypatch.setattr(tools_module, "convert_file", fake_convert_file)

    payload = convert(str(source))

    assert payload["truncated"] is True
    assert len(payload["markdown"]) == INLINE_LIMIT
    # The file on disk always carries the whole thing, even when the inline text is capped.
    assert Path(payload["markdown_path"]).read_text(encoding="utf-8") == long_markdown


def test_convert_raises_for_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConversionError):
        convert(str(tmp_path / "missing.docx"))
