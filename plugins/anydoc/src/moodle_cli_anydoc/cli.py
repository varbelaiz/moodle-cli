"""`moodle anydoc convert` and `moodle anydoc fetch` -- the CLI surface for markdown
conversion.

`convert` streams an ok/FAIL line per file rather than offering `--json`, the same
choice `course download` makes: this reports on a batch of local file operations, not a
single structured answer. `fetch` reaches the campus, so it goes through the same error
handling core commands use.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, ParamSpec, TypeVar

import typer
from rich.console import Console
from rich.markup import escape

from moodle_cli.errors import MoodleError
from moodle_cli_anydoc.convert import ConversionError, convert_file
from moodle_cli_anydoc.fetch import fetch_and_convert

console = Console()
err_console = Console(stderr=True)

app = typer.Typer(help="Convert course files to markdown.")

P = ParamSpec("P")
R = TypeVar("R")


def _handle_errors(func: Callable[P, R]) -> Callable[P, R]:
    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return func(*args, **kwargs)
        except (MoodleError, ConversionError, ValueError) as exc:
            err_console.print(f"[red]Error:[/red] {escape(str(exc))}")
            raise typer.Exit(1) from exc

    return wrapper


@app.command("convert")
def convert_command(
    paths: Annotated[
        list[Path],
        typer.Argument(help="Files to convert, as put on disk by `course download`."),
    ],
    ocr: Annotated[
        bool,
        typer.Option(
            "--ocr",
            help="Convert via Firecrawl Parse (hosted, OCR) instead of locally. "
            "Requires FIRECRAWL_KEY; sends each file to a third-party API.",
        ),
    ] = False,
) -> None:
    """Convert one or more files already on disk to markdown, writing `<name>.md` alongside each."""
    failed = 0
    for path in paths:
        try:
            converted = convert_file(path, ocr=ocr)
        except ConversionError as exc:
            failed += 1
            err_console.print(f"[red]FAIL[/red] {escape(str(exc))}")
            continue
        console.print(
            f"[green]ok[/green]   {escape(str(path))} -> {escape(str(converted.markdown_path))}"
        )

    if failed:
        raise typer.Exit(1)


@app.command("fetch")
@_handle_errors
def fetch_command(
    course: Annotated[str, typer.Argument(help="Course id or shortname, e.g. 29272 or IOS460.")],
    filename: Annotated[str, typer.Argument(help="Exact filename, as shown by `course contents`.")],
    section: Annotated[
        int | None,
        typer.Option("--section", help="Narrow to one section, if the name matches more than one."),
    ] = None,
    ocr: Annotated[
        bool,
        typer.Option(
            "--ocr",
            help="Convert via Firecrawl Parse (hosted, OCR) instead of locally. "
            "Requires FIRECRAWL_KEY; sends the file to a third-party API.",
        ),
    ] = False,
) -> None:
    """Fetch one course file and convert it to markdown, writing `<name>.md` alongside it."""
    converted = fetch_and_convert(course, filename, section=section, ocr=ocr)
    console.print(
        f"[green]ok[/green]   {escape(str(converted.source))} -> "
        f"{escape(str(converted.markdown_path))}"
    )
