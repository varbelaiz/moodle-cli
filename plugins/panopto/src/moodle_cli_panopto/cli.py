"""`moodle panopto list`, `moodle panopto download` and `moodle panopto get` -- the CLI
surface for a course's Panopto recordings and their transcripts.
"""

from __future__ import annotations

import functools
import json
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, ParamSpec, TypeVar

import typer
from rich.console import Console
from rich.markup import escape

from moodle_cli.errors import MoodleError
from moodle_cli_panopto.errors import PanoptoError
from moodle_cli_panopto.fetch import download_transcripts, get_transcript, list_course_recordings
from moodle_cli_panopto.recordings import select_sessions
from moodle_cli_panopto.srt import SrtError

console = Console()
err_console = Console(stderr=True)

app = typer.Typer(help="List and transcribe a course's Panopto recordings.")

P = ParamSpec("P")
R = TypeVar("R")

CourseArg = Annotated[str, typer.Argument(help="Course id or shortname, e.g. 29272 or IOS460.")]
LanguageOpt = Annotated[
    int | None,
    typer.Option("--language", help="Caption language code, if the recording has more than one."),
]


def _handle_errors(func: Callable[P, R]) -> Callable[P, R]:
    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return func(*args, **kwargs)
        except (MoodleError, PanoptoError, SrtError, ValueError) as exc:
            err_console.print(f"[red]Error:[/red] {escape(str(exc))}")
            raise typer.Exit(1) from exc

    return wrapper


@app.command("list")
@_handle_errors
def list_command(
    course: CourseArg,
    as_json: Annotated[bool, typer.Option("--json", help="Emit JSON instead of a table.")] = False,
) -> None:
    """List a course's Panopto recordings. Never reaches a Panopto host."""
    _resolved, recordings = list_course_recordings(course)
    if as_json:
        payload = [{"id": r.id, "name": r.name} for r in recordings]
        console.print_json(json.dumps(payload, ensure_ascii=False))
        return
    if not recordings:
        console.print("No recordings.")
        return
    for recording in recordings:
        console.print(f"{recording.id}  {escape(recording.name)}")


@app.command("get")
@_handle_errors
def get_command(
    course: CourseArg,
    session: Annotated[str, typer.Argument(help="Delivery id or a name substring.")],
    language: LanguageOpt = None,
) -> None:
    """Print one session's transcript as markdown to stdout. Writes nothing to disk."""
    content = get_transcript(course, session, language=language)
    console.print(content.markdown, highlight=False, soft_wrap=True)


@app.command("download")
@_handle_errors
def download_command(
    course: CourseArg,
    session: Annotated[
        list[str] | None,
        typer.Option("--session", help="Exact delivery id or display name. Repeatable."),
    ] = None,
    match: Annotated[
        list[str] | None, typer.Option("--match", help="Glob on the display name. Repeatable.")
    ] = None,
    language: LanguageOpt = None,
    output: Annotated[
        Path | None,
        typer.Option(
            "--output", "-o", help="Destination directory. Default: ./<shortname>/Panopto/"
        ),
    ] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="List what would be downloaded, write nothing.")
    ] = False,
    overwrite: Annotated[
        bool, typer.Option("--overwrite", help="Re-fetch transcripts that already exist.")
    ] = False,
) -> None:
    """Fetch and write transcripts for a course's recordings as markdown.

    --session and --match compose as a union, matching exactly like `course download`'s
    --file/--match. Without either, every recording in the course is fetched.
    """
    resolved, recordings = list_course_recordings(course)
    names = set(session) if session else None
    patterns = set(match) if match else None
    selected = select_sessions(recordings, names, patterns)
    if (names or patterns) and not selected:
        raise ValueError("no recording matches --session/--match")

    failed = 0
    for outcome in download_transcripts(
        resolved, selected, language=language, output=output, overwrite=overwrite, dry_run=dry_run
    ):
        label = escape(outcome.recording.name)
        if outcome.status == "downloaded":
            console.print(f"[green]ok[/green]      {label} -> {escape(str(outcome.destination))}")
        elif outcome.status == "skipped":
            console.print(f"[dim]skip[/dim]    {label}")
        elif outcome.status == "planned":
            console.print(f"[cyan]planned[/cyan] {label} -> {escape(str(outcome.destination))}")
        else:
            failed += 1
            err_console.print(f"[red]FAIL[/red]    {label}: {escape(outcome.error or '')}")

    if failed:
        raise typer.Exit(1)
