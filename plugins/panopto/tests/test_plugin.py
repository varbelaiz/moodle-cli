"""Tests for the Plugin contract this package implements."""

from __future__ import annotations

from moodle_cli_panopto import PanoptoPlugin
from typer.testing import CliRunner

runner = CliRunner()


def test_name_matches_the_extra_and_directory() -> None:
    """`moodle plugins install panopto` and the mounted command group must agree."""
    assert PanoptoPlugin.name == "panopto"


def test_commands_mounts_list_download_and_get() -> None:
    app = PanoptoPlugin().commands()
    assert app is not None

    result = runner.invoke(app, ["--help"])
    assert "list" in result.stdout
    assert "download" in result.stdout
    assert "get" in result.stdout


def test_tools_exposes_the_three_mcp_tools() -> None:
    tools = PanoptoPlugin().tools()
    assert [tool.__name__ for tool in tools] == [
        "list_recordings",
        "download_transcript",
        "get_transcript",
    ]
