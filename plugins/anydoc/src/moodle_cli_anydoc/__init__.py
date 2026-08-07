"""Convert course files already on disk to markdown, via firecrawl-anydoc.

Purely local: nothing here reaches the campus, so this plugin needs no client and no
token. It operates on files `course download` (or `download_course_files`) already put
on disk.
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
        from moodle_cli_anydoc.tools import convert

        return (convert,)
