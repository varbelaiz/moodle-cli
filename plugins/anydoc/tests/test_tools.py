"""Tests for the `anydoc_convert_to_markdown` and `anydoc_get_markdown` MCP tools."""

from __future__ import annotations

from pathlib import Path

import pytest
from moodle_cli_anydoc import tools as tools_module
from moodle_cli_anydoc.convert import Converted
from moodle_cli_anydoc.tools import INLINE_LIMIT, convert_to_markdown, get_markdown

# -- convert_to_markdown --------------------------------------------------------------


def test_convert_to_markdown_returns_a_path_only_manifest(tmp_path: Path) -> None:
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    a.write_text("x,y\n1,2\n", encoding="utf-8")
    b.write_text("x,y\n3,4\n", encoding="utf-8")

    results = convert_to_markdown([str(a), str(b)])

    assert results == [
        {"path": str(a), "markdown_path": str(tmp_path / "a.csv.md"), "status": "converted"},
        {"path": str(b), "markdown_path": str(tmp_path / "b.csv.md"), "status": "converted"},
    ]


def test_convert_to_markdown_keeps_going_after_one_failure(tmp_path: Path) -> None:
    missing = tmp_path / "missing.docx"
    good = tmp_path / "grades.csv"
    good.write_text("a,b\n1,2\n", encoding="utf-8")

    results = convert_to_markdown([str(missing), str(good)])

    assert results[0]["status"] == "error"
    assert "error" in results[0]
    assert results[1] == {
        "path": str(good),
        "markdown_path": str(tmp_path / "grades.csv.md"),
        "status": "converted",
    }


# -- get_markdown ----------------------------------------------------------------------


def test_get_markdown_returns_content_and_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "grades.csv"
    markdown_path = tmp_path / "grades.csv.md"
    monkeypatch.setattr(
        tools_module,
        "fetch_and_convert",
        lambda course, filename, section=None, ocr=False: Converted(source, "| 1 |", markdown_path),
    )

    payload = get_markdown("IOS460", "grades.csv")

    assert payload == {
        "path": str(source),
        "markdown_path": str(markdown_path),
        "markdown": "| 1 |",
        "truncated": False,
    }


def test_get_markdown_truncates_long_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "big.pdf"
    markdown_path = tmp_path / "big.pdf.md"
    long_markdown = "x" * (INLINE_LIMIT + 500)
    monkeypatch.setattr(
        tools_module,
        "fetch_and_convert",
        lambda course, filename, section=None, ocr=False: Converted(
            source, long_markdown, markdown_path
        ),
    )

    payload = get_markdown("IOS460", "big.pdf")

    assert payload["truncated"] is True
    assert len(payload["markdown"]) == INLINE_LIMIT
    # The caller still gets the full path; only the inline text is capped.
    assert payload["markdown_path"] == str(markdown_path)


def test_get_markdown_passes_section_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, object] = {}

    def fake_fetch_and_convert(
        course: str, filename: str, section: int | None = None, ocr: bool = False
    ) -> Converted:
        seen["section"] = section
        return Converted(tmp_path / "a.csv", "ok", tmp_path / "a.csv.md")

    monkeypatch.setattr(tools_module, "fetch_and_convert", fake_fetch_and_convert)

    get_markdown("IOS460", "notes.csv", section=2)

    assert seen["section"] == 2


def test_get_markdown_passes_ocr_through(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_fetch_and_convert(
        course: str, filename: str, section: int | None = None, ocr: bool = False
    ) -> Converted:
        seen["ocr"] = ocr
        return Converted(tmp_path / "a.pdf", "ok", tmp_path / "a.pdf.md")

    monkeypatch.setattr(tools_module, "fetch_and_convert", fake_fetch_and_convert)

    get_markdown("IOS460", "scan.pdf", ocr=True)

    assert seen["ocr"] is True


def test_convert_to_markdown_passes_ocr_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, object] = {}

    def fake_convert_file(path: Path, *, ocr: bool = False) -> Converted:
        seen["ocr"] = ocr
        return Converted(path, "ok", path.with_name(f"{path.name}.md"))

    monkeypatch.setattr(tools_module, "convert_file", fake_convert_file)

    convert_to_markdown([str(tmp_path / "scan.pdf")], ocr=True)

    assert seen["ocr"] is True
