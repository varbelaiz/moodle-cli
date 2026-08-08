"""Convert course files to markdown, via firecrawl-anydoc.

Two capabilities, deliberately split: converting a batch of files already on disk needs
no client and no token, while fetching one course file by name reaches the campus itself
through the same client and download machinery `course download` uses.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from moodle_cli.plugins import Plugin

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    import typer

__all__ = ["AnydocPlugin"]


class AnydocPlugin(Plugin):
    name = "anydoc"

    def commands(self) -> typer.Typer | None:
        from moodle_cli_anydoc.cli import app

        return app

    def tools(self) -> Sequence[Callable[..., Any]]:
        from moodle_cli_anydoc.tools import convert_to_markdown, get_markdown

        return (convert_to_markdown, get_markdown)
