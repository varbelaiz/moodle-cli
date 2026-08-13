"""List a course's Panopto recordings and convert their transcripts to markdown.

Two capabilities, split by what each is for: `list`/`list_recordings` never leaves
Moodle (the course's own Panopto block, over internal AJAX); `download`/`get` reach a
Panopto host for the transcript itself, via a cookie-authenticated Moodle login and an
LTI-launch relay -- the web-service token this tool otherwise runs on covers none of it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from moodle_cli.plugins import Plugin

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    import typer

__all__ = ["PanoptoPlugin"]


class PanoptoPlugin(Plugin):
    name = "panopto"

    def commands(self) -> typer.Typer | None:
        from moodle_cli_panopto.cli import app

        return app

    def tools(self) -> Sequence[Callable[..., Any]]:
        from moodle_cli_panopto.tools import download_transcript, get_transcript, list_recordings

        return (list_recordings, download_transcript, get_transcript)
