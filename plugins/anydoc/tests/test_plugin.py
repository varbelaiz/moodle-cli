"""Tests for the Plugin contract this package implements."""

from __future__ import annotations

from moodle_cli_anydoc import AnydocPlugin
from typer.testing import CliRunner

runner = CliRunner()


def test_name_matches_the_extra_and_directory() -> None:
    """`moodle plugins install anydoc` and the mounted command group must agree."""
    assert AnydocPlugin.name == "anydoc"


def test_commands_mounts_convert_and_fetch() -> None:
    app = AnydocPlugin().commands()
    assert app is not None

    result = runner.invoke(app, ["--help"])
    assert "convert" in result.stdout
    assert "fetch" in result.stdout


def test_tools_exposes_convert_to_markdown_and_get_markdown() -> None:
    tools = AnydocPlugin().tools()
    assert [tool.__name__ for tool in tools] == ["convert_to_markdown", "get_markdown"]
