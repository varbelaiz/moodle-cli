"""`moodle anydoc convert` -- the CLI surface for local markdown conversion.

Streams an ok/FAIL line per file rather than offering `--json`, the same choice
`course download` makes: this reports on a batch of local file operations, not a single
structured answer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape

from moodle_cli_anydoc.convert import ConversionError, convert_file

console = Console()
err_console = Console(stderr=True)

app = typer.Typer(help="Convert downloaded course files to markdown.")


@app.callback()
def _callback() -> None:
    # A Typer app with exactly one command and no callback collapses "moodle anydoc
    # convert PATH" into "moodle anydoc PATH", dropping the verb. This callback exists
    # only to keep that from happening -- a second command can drop it later.
    pass


@app.command("convert")
def convert_command(
    paths: Annotated[
        list[Path],
        typer.Argument(help="Files to convert, as put on disk by `course download`."),
    ],
) -> None:
    """Convert one or more files to markdown, writing `<name>.md` alongside each."""
    failed = 0
    for path in paths:
        try:
            converted = convert_file(path)
        except ConversionError as exc:
            failed += 1
            err_console.print(f"[red]FAIL[/red] {escape(str(exc))}")
            continue
        console.print(
            f"[green]ok[/green]   {escape(str(path))} -> {escape(str(converted.markdown_path))}"
        )

    if failed:
        raise typer.Exit(1)
