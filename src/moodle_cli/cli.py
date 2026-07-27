"""Typer command line interface."""

from __future__ import annotations

import functools
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, ParamSpec, TypeVar

import httpx
import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from moodle_cli.auth import TokenStore, mint_token, resolve_token
from moodle_cli.client import MoodleClient
from moodle_cli.config import load_config
from moodle_cli.downloads import (
    DownloadStatus,
    PlannedDownload,
    download_file,
    plan_downloads,
    sanitize,
)
from moodle_cli.errors import MoodleError
from moodle_cli.models import Participant

console = Console()
err_console = Console(stderr=True)

app = typer.Typer(
    help="Access a Moodle campus: courses, contents, downloads and participants.",
    no_args_is_help=True,
    add_completion=False,
)
auth_app = typer.Typer(help="Manage authentication.", no_args_is_help=True)
courses_app = typer.Typer(help="Work with your enrolled courses.", no_args_is_help=True)
course_app = typer.Typer(help="Work with a single course.", no_args_is_help=True)
app.add_typer(auth_app, name="auth")
app.add_typer(courses_app, name="courses")
app.add_typer(course_app, name="course")


class View(StrEnum):
    ALL = "all"
    ALL_INCLUDING_HIDDEN = "all-including-hidden"
    IN_PROGRESS = "in-progress"
    FUTURE = "future"
    PAST = "past"
    STARRED = "starred"
    HIDDEN = "hidden"


class Sort(StrEnum):
    NAME = "name"
    LAST_ACCESSED = "last-accessed"


CourseArg = Annotated[str, typer.Argument(help="Course id or shortname, e.g. 29272 or IOS460.")]
JsonOpt = Annotated[bool, typer.Option("--json", help="Emit JSON instead of a table.")]

P = ParamSpec("P")
R = TypeVar("R")


def handle_errors(func: Callable[P, R]) -> Callable[P, R]:
    """Turn library errors into a clean message and a non-zero exit.

    This lives on the commands rather than only in `main()` so the behaviour is the same
    however the app is invoked, including from tests.
    """

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return func(*args, **kwargs)
        except MoodleError as exc:
            err_console.print(f"[red]Error:[/red] {escape(str(exc))}")
            raise typer.Exit(1) from exc

    return wrapper


@contextmanager
def _client() -> Iterator[MoodleClient]:
    config = load_config()
    with MoodleClient(config.base_url, resolve_token(config)) as client:
        yield client


def _emit_json(payload: Any) -> None:
    console.print_json(json.dumps(payload, ensure_ascii=False, default=str))


def _human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def _format_epoch(value: int) -> str:
    return datetime.fromtimestamp(value).strftime("%Y-%m-%d") if value else "-"


def _format_year(value: int) -> str:
    """Start year is the only recency signal available: no course here sets an end date."""
    return datetime.fromtimestamp(value).strftime("%Y") if value else "-"


# -- auth ------------------------------------------------------------------------


@auth_app.command("login")
@handle_errors
def auth_login(
    username: Annotated[
        str | None, typer.Option("--username", "-u", help="Campus username.")
    ] = None,
) -> None:
    """Mint a web-service token and store it in the system keyring.

    The password is prompted for and never accepted as an argument, which would leave it in
    your shell history. Once the token is stored you can remove MOODLE_PASS from .env.
    """
    config = load_config()
    user = username or config.username or typer.prompt("Username")
    password = config.password or typer.prompt("Password", hide_input=True)

    token = mint_token(config.base_url, user, password)
    stored = TokenStore().set(config.keyring_key, token)

    with MoodleClient(config.base_url, token) as client:
        info = client.get_site_info()

    console.print(f"[green]Logged in[/green] as {info.fullname} (id {info.userid})")
    console.print(f"  site: {info.sitename}  ({info.release})")
    if stored:
        console.print("  token stored in the system keyring")
    else:
        console.print(
            "[yellow]  no keyring backend available; set MOODLE_TOKEN to reuse this token[/yellow]"
        )


@auth_app.command("status")
@handle_errors
def auth_status() -> None:
    """Show whether a usable token exists, and who it belongs to."""
    config = load_config()
    token = resolve_token(config, allow_mint=False)
    with MoodleClient(config.base_url, token) as client:
        info = client.get_site_info()
    console.print(f"[green]Authenticated[/green] as {info.fullname} (id {info.userid})")
    console.print(f"  site: {info.sitename}")
    console.print(f"  functions available: {len(info.function_names)}")
    console.print(f"  file downloads allowed: {info.downloadfiles}")


@auth_app.command("logout")
@handle_errors
def auth_logout() -> None:
    """Delete the stored token from the keyring."""
    config = load_config()
    if TokenStore().delete(config.keyring_key):
        console.print("[green]Token deleted from the keyring.[/green]")
    else:
        console.print("[yellow]No stored token to delete.[/yellow]")


# -- courses ---------------------------------------------------------------------


@courses_app.command("list")
@handle_errors
def courses_list(
    view: Annotated[View, typer.Option("--view", help="Which courses to include.")] = View.ALL,
    sort: Annotated[Sort, typer.Option("--sort", help="Ordering.")] = Sort.NAME,
    as_json: JsonOpt = False,
) -> None:
    """List your enrolled courses.

    Note on --view: the time-based filters depend on courses having an end date, and this
    campus never sets one. In practice 'in-progress' returns everything and 'past'/'future'
    return nothing; only 'all', 'starred' and 'hidden' discriminate.
    """
    with _client() as client:
        courses = client.list_courses(view=view.value, sort=sort.value)

    if as_json:
        _emit_json([c.model_dump(mode="json") for c in courses])
        return

    # Only `name` flexes; everything else is fixed and no-wrap, so a narrow terminal
    # ellipsizes the name instead of crushing the columns that identify the course.
    # Category is dropped for width and lives in --json.
    table = Table(title=f"{len(courses)} courses ({view.value}, by {sort.value})", expand=True)
    table.add_column("id", justify="right", style="dim", no_wrap=True)
    table.add_column("shortname", no_wrap=True)
    table.add_column("name", ratio=1, min_width=20, no_wrap=True, overflow="ellipsis")
    table.add_column("year", justify="right", style="dim", no_wrap=True)
    table.add_column("*", justify="center", no_wrap=True)
    for course in courses:
        table.add_row(
            str(course.id),
            course.shortname,
            _short_name(course.fullname, course.shortname),
            _format_year(course.startdate),
            "*" if course.isfavourite else "",
        )
    console.print(table)


def _short_name(fullname: str, shortname: str) -> str:
    """Drop the course code the fullname repeats from the shortname.

    Campus fullnames read "I406 - Criptografía y Ciberseguridad (grupo 2) G:2 Teó 1 - ...",
    where the leading code is already its own column.
    """
    code = shortname.split(" - ")[0].strip()
    if code and fullname.startswith(f"{code} - "):
        return fullname[len(code) + 3 :]
    return fullname


# -- course ----------------------------------------------------------------------


@course_app.command("contents")
@handle_errors
def course_contents(course: CourseArg, as_json: JsonOpt = False) -> None:
    """Show a course's sections, activities and downloadable files."""
    with _client() as client:
        resolved = client.resolve_course(course)
        sections = client.get_course_contents(resolved.id)

    if as_json:
        _emit_json([s.model_dump(mode="json") for s in sections])
        return

    console.print(f"[bold]{resolved.shortname}[/bold] — {resolved.fullname}\n")
    for section in sections:
        files = sum(len(m.files) for m in section.modules)
        suffix = f"  [dim]({files} files)[/dim]" if files else ""
        console.print(f"[bold cyan]{section.section:>2}. {section.name}[/bold cyan]{suffix}")
        for module in section.modules:
            marker = "" if module.uservisible else " [dim](hidden)[/dim]"
            console.print(f"     [dim]{module.modname:<10}[/dim] {module.name}{marker}")
            for file in module.files:
                console.print(
                    f"       [green]-[/green] {file.filename} "
                    f"[dim]({_human_size(file.filesize)})[/dim]"
                )
        console.print()


@course_app.command("download")
@handle_errors
def course_download(
    course: CourseArg,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Destination directory. Default: ./<shortname>/"),
    ] = None,
    sections: Annotated[
        list[int] | None,
        typer.Option("--section", help="Only this section number. Repeatable."),
    ] = None,
    types: Annotated[
        list[str] | None,
        typer.Option("--type", help="Only these module types, e.g. resource. Repeatable."),
    ] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="List what would be downloaded, write nothing.")
    ] = False,
    overwrite: Annotated[
        bool, typer.Option("--overwrite", help="Re-download files that already exist.")
    ] = False,
) -> None:
    """Download a course's files, mirroring its section structure."""
    config = load_config()
    token = resolve_token(config)

    with MoodleClient(config.base_url, token) as client:
        resolved = client.resolve_course(course)
        contents = client.get_course_contents(resolved.id)

    root = output or Path(sanitize(resolved.shortname, fallback=str(resolved.id)))
    planned = plan_downloads(
        contents,
        root,
        only_sections=set(sections) if sections else None,
        only_modtypes=set(types) if types else None,
    )

    if not planned:
        console.print("[yellow]No matching files.[/yellow]")
        return

    total = sum(p.file.filesize for p in planned)
    console.print(
        f"[bold]{resolved.shortname}[/bold]: {len(planned)} files, {_human_size(total)} -> {root}/"
    )

    if dry_run:
        _print_plan(planned, root)
        return

    downloaded = skipped = 0
    with httpx.Client(timeout=300, follow_redirects=True) as http:
        for item in planned:
            relative = item.destination.relative_to(root)
            try:
                result = download_file(
                    http, item.file, token, item.destination, overwrite=overwrite
                )
            except MoodleError as exc:
                err_console.print(f"  [red]FAIL[/red] {escape(str(relative))}: {escape(str(exc))}")
                continue
            if result.status is DownloadStatus.SKIPPED:
                skipped += 1
                console.print(f"  [dim]skip[/dim] {escape(str(relative))}")
            else:
                downloaded += 1
                console.print(
                    f"  [green]ok[/green]   {escape(str(relative))} "
                    f"[dim]({_human_size(result.size)})[/dim]"
                )

    failed = len(planned) - downloaded - skipped
    summary = f"\n{downloaded} downloaded, {skipped} already present"
    if failed:
        summary += f", [red]{failed} failed[/red]"
    console.print(summary)
    if failed:
        raise typer.Exit(1)


def _print_plan(planned: list[PlannedDownload], root: Path) -> None:
    table = Table(show_header=True)
    table.add_column("size", justify="right")
    table.add_column("type", style="dim")
    table.add_column("destination")
    for item in planned:
        table.add_row(
            _human_size(item.file.filesize),
            item.module.modname,
            str(item.destination.relative_to(root)),
        )
    console.print(table)


@course_app.command("participants")
@handle_errors
def course_participants(
    course: CourseArg,
    role: Annotated[
        str | None, typer.Option("--role", help="Filter by role shortname, e.g. student.")
    ] = None,
    emails: Annotated[
        bool, typer.Option("--emails", help="Include email addresses (hidden by default).")
    ] = False,
    as_json: JsonOpt = False,
) -> None:
    """List the people enrolled in a course.

    Email addresses are withheld unless --emails is passed: the API returns them for every
    participant, and they are not something to spill into a terminal or a log by default.
    """
    with _client() as client:
        resolved = client.resolve_course(course)
        participants = client.get_participants(resolved.id)

    if role:
        needle = role.casefold()
        participants = [p for p in participants if needle in {r.casefold() for r in p.role_names}]

    if as_json:
        _emit_json([_participant_payload(p, emails) for p in participants])
        return

    table = Table(title=f"{len(participants)} participants in {resolved.shortname}")
    table.add_column("name")
    table.add_column("roles", style="dim")
    if emails:
        table.add_column("email")
    table.add_column("last access", justify="right", style="dim")
    for person in participants:
        row = [person.fullname, ", ".join(person.role_names) or "-"]
        if emails:
            row.append(person.email or "-")
        row.append(_format_epoch(person.lastcourseaccess))
        table.add_row(*row)
    console.print(table)


def _participant_payload(person: Participant, emails: bool) -> dict[str, Any]:
    payload = person.model_dump(mode="json")
    if not emails:
        payload.pop("email", None)
    return payload


def main() -> None:
    """Entry point that turns library errors into clean CLI failures."""
    try:
        app()
    except MoodleError as exc:
        err_console.print(f"[red]Error:[/red] {escape(str(exc))}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
