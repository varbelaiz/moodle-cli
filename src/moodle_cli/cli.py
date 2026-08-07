"""Typer command line interface."""

from __future__ import annotations

import functools
import json
import textwrap
from collections.abc import Callable, Iterator
from contextlib import contextmanager
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
    iter_course_files,
    plan_downloads,
    sanitize,
)
from moodle_cli.errors import MoodleError
from moodle_cli.models import (
    Announcement,
    Assignment,
    Participant,
    Section,
    epoch_to_datetime,
)
from moodle_cli.search import SearchHit, search_contents

console = Console()
err_console = Console(stderr=True)

app = typer.Typer(
    help=(
        "Access a Moodle campus: courses, contents, downloads, participants, "
        "announcements, assignments, quizzes and grades."
    ),
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


def _format_epoch(value: int, fmt: str = "%Y-%m-%d") -> str:
    """Render a Moodle timestamp, going through the one shared conversion.

    Converting here rather than from the raw epoch is what keeps this surface and the MCP
    server on the same calendar day for an evening event.
    """
    moment = epoch_to_datetime(value)
    return moment.strftime(fmt) if moment else "-"


def _plural(count: int, noun: str) -> str:
    return noun if count == 1 else f"{noun}s"


def _format_year(value: int) -> str:
    """Start year is the only recency signal available: no course here sets an end date."""
    return _format_epoch(value, "%Y")


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


@courses_app.command("grades")
@handle_errors
def courses_grades(as_json: JsonOpt = False) -> None:
    """Show a grade summary across every enrolled course.

    Works even for a course whose gradebook is not open to students. For a per-item
    breakdown of one course, use `course grades` instead.
    """
    with _client() as client:
        course_names = _course_names(client)
        overview = client.get_grade_overview()

    if as_json:
        _emit_json(
            [
                {"course": course_names.get(g.courseid, str(g.courseid)), "grade": g.grade}
                for g in overview
            ]
        )
        return

    table = Table(title=f"Grade summary ({len(overview)} {_plural(len(overview), 'course')})")
    table.add_column("course")
    table.add_column("grade", justify="right")
    for g in overview:
        table.add_row(escape(course_names.get(g.courseid, str(g.courseid))), g.grade or "-")
    console.print(table)


@courses_app.command("assignments")
@handle_errors
def courses_assignments(as_json: JsonOpt = False) -> None:
    """List assignments and due dates across every enrolled course.

    Ordered by due date, undated last, so the next deadline is at the top. For one course,
    use `course assignments`.
    """
    with _client() as client:
        course_names = _course_names(client)
        assignments = sorted(client.get_assignments(), key=_by_due_date)

    if as_json:
        _emit_json([a.model_dump(mode="json") for a in assignments])
        return

    count = len(assignments)
    table = Table(title=f"{count} {_plural(count, 'assignment')}")
    table.add_column("id", justify="right", style="dim")
    table.add_column("course", no_wrap=True)
    table.add_column("name")
    table.add_column("due", justify="right", style="dim")
    table.add_column("grade", justify="right", style="dim")
    for a in assignments:
        table.add_row(
            str(a.id),
            escape(course_names.get(a.course, str(a.course))),
            escape(a.name),
            _format_epoch(a.duedate),
            _grade_cell(a),
        )
    console.print(table)


def _by_due_date(assignment: Assignment) -> tuple[bool, int]:
    """Sort undated assignments after dated ones: 0 means "no due date", not "the epoch"."""
    return (assignment.duedate == 0, assignment.duedate)


def _course_names(client: MoodleClient) -> dict[int, str]:
    """Shortname per course id, for labelling rows that carry only an id.

    Includes courses hidden from the dashboard: the grade and assignment endpoints answer
    for every enrolment, so anything narrower leaves a bare id in the output.
    """
    return {c.id: c.shortname for c in client.list_courses(view="all-including-hidden")}


def _short_name(fullname: str, shortname: str) -> str:
    """Drop the course code the fullname repeats from the shortname.

    Campus fullnames read "I406 - Criptografía y Ciberseguridad (grupo 2) G:2 Teó 1 - ...",
    where the leading code is already its own column.
    """
    code = shortname.split(" - ")[0].strip()
    if code and fullname.startswith(f"{code} - "):
        return fullname[len(code) + 3 :]
    return fullname


@courses_app.command("search")
@handle_errors
def courses_search(
    query: Annotated[str, typer.Argument(help="Text to look for in names, case-insensitive.")],
    as_json: JsonOpt = False,
) -> None:
    """Search section, activity, file and link names across every enrolled course.

    A link matches on its destination as well as on its label, so a bare domain such as
    github.com finds it. The match column names what was hit; when it is an activity name,
    the files and links shown are the activity's whole contents rather than a filtered set.
    """
    with _client() as client:
        results = search_contents(client, query)

    if as_json:
        _emit_json(results.as_payload())
        return

    if not results.hits:
        console.print("[yellow]No matches.[/yellow]")
        return

    count = len(results.hits)
    table = Table(title=f"{count} {_plural(count, 'result')} for {query!r}", expand=True)
    table.add_column("course", no_wrap=True)
    table.add_column("section", style="dim", no_wrap=True, overflow="ellipsis")
    table.add_column("match", style="dim", no_wrap=True)
    table.add_column("activity", ratio=1, min_width=16, no_wrap=True, overflow="ellipsis")
    table.add_column("files and links", ratio=1, min_width=16, overflow="fold")
    for hit in results.hits:
        table.add_row(
            hit.course,
            f"{hit.section_number}. {hit.section}",
            hit.kind.value,
            hit.module or "-",
            _hit_contents(hit),
        )
    console.print(table)
    if results.truncated:
        console.print("[yellow]More matches than shown; narrow the query.[/yellow]")


def _hit_contents(hit: SearchHit) -> str:
    names = [f.filename for f in hit.files] + [link.fileurl or "" for link in hit.links]
    return "\n".join(names) or "-"


# -- course ----------------------------------------------------------------------


@course_app.command("contents")
@handle_errors
def course_contents(course: CourseArg, as_json: JsonOpt = False) -> None:
    """Show a course's sections, activities, downloadable files and external links."""
    with _client() as client:
        resolved = client.resolve_course(course)
        sections = client.get_course_contents(resolved.id)

    if as_json:
        _emit_json([s.model_dump(mode="json") for s in sections])
        return

    console.print(f"[bold]{escape(resolved.shortname)}[/bold] — {escape(resolved.fullname)}\n")
    for section in sections:
        files = sum(len(m.files) for m in section.modules)
        links = sum(len(m.links) for m in section.modules)
        counts = [c for c in [_count(files, "file"), _count(links, "link")] if c]
        suffix = f"  [dim]({', '.join(counts)})[/dim]" if counts else ""
        console.print(
            f"[bold cyan]{section.section:>2}. {escape(section.name)}[/bold cyan]{suffix}"
        )
        for module in section.modules:
            marker = "" if module.uservisible else " [dim](hidden)[/dim]"
            console.print(f"     [dim]{module.modname:<10}[/dim] {escape(module.name)}{marker}")
            for file in module.files:
                # Size leads so a long filename wrapping cannot orphan it on its own line.
                size = _human_size(file.filesize).rjust(9)
                console.print(f"       [dim]{size}[/dim]  {escape(file.filename)}")
            for link in module.links:
                console.print(f"       [dim]{'link':>9}[/dim]  {escape(link.fileurl or '')}")
        console.print()


def _count(n: int, noun: str) -> str:
    return f"{n} {_plural(n, noun)}" if n else ""


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
    names: Annotated[
        list[str] | None,
        typer.Option(
            "--file",
            help="Exact filename, as shown by `course contents`. Repeatable. "
            "Fails if a name matches nothing.",
        ),
    ] = None,
    patterns: Annotated[
        list[str] | None,
        typer.Option("--match", help="Glob on the filename, e.g. '*.pdf'. Repeatable."),
    ] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="List what would be downloaded, write nothing.")
    ] = False,
    overwrite: Annotated[
        bool, typer.Option("--overwrite", help="Re-download files that already exist.")
    ] = False,
) -> None:
    """Download a course's files, mirroring its section structure.

    Selectors compose: --section and --type narrow by structure, --file and --match by
    filename. A --file name that matches nothing is an error rather than a silent
    zero-file download, so a typo fails loudly.
    """
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
        only_names=set(names) if names else None,
        only_patterns=patterns or None,
    )

    if names:
        _reject_unknown_names(names, planned, contents)

    if not planned:
        console.print("[yellow]No matching files.[/yellow]")
        return

    total = sum(p.file.filesize for p in planned)
    console.print(
        f"[bold]{resolved.shortname}[/bold]: {len(planned)} "
        f"{_plural(len(planned), 'file')}, {_human_size(total)} -> {root}/"
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


def _reject_unknown_names(
    requested: list[str], planned: list[PlannedDownload], contents: list[Section]
) -> None:
    """Fail on a --file name that selected nothing.

    Distinguishes a typo from a name excluded by another filter, because the two need
    different fixes and the symptom is identical.
    """
    selected = {p.file.filename for p in planned}
    missing = [name for name in requested if name not in selected]
    if not missing:
        return

    in_course = {f.filename for _, _, f in iter_course_files(contents)}
    for name in missing:
        reason = (
            "excluded by --section/--type" if name in in_course else "no such file in this course"
        )
        err_console.print(f"[red]Error:[/red] {escape(name)}: {reason}")
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


@course_app.command("announcements")
@handle_errors
def course_announcements(course: CourseArg, as_json: JsonOpt = False) -> None:
    """List announcements from a course's news forum, newest first.

    Only a forum Moodle marks as "news" carries announcements; a course without one
    prints nothing.
    """
    with _client() as client:
        resolved = client.resolve_course(course)
        announcements = client.get_announcements([resolved.id])

    if as_json:
        _emit_json([_announcement_payload(a, resolved.shortname) for a in announcements])
        return

    if not announcements:
        console.print("[yellow]No announcements.[/yellow]")
        return

    for a in announcements:
        pin = " [yellow](pinned)[/yellow]" if a.pinned else ""
        console.print(f"[bold]{escape(a.subject)}[/bold]{pin}")
        console.print(
            f"  [dim]{_format_epoch(a.created, '%Y-%m-%d %H:%M')} — {escape(a.userfullname)}[/dim]"
        )
        console.print(textwrap.indent(escape(a.message_text), "  "))
        console.print()


def _announcement_payload(announcement: Announcement, course: str) -> dict[str, Any]:
    """Build the JSON body field by field, matching the MCP tool key for key.

    ``message`` carries plain text on both surfaces; a model dump would ship raw HTML
    here and drop the derived fields, so a consumer that learned the schema from one
    surface would silently mis-read the other.
    """
    return {
        "id": announcement.id,
        "course": course,
        "subject": announcement.subject,
        "message": announcement.message_text,
        "author": announcement.userfullname,
        "posted_at": announcement.posted_at.isoformat() if announcement.posted_at else None,
        "replies": announcement.numreplies,
        "pinned": announcement.pinned,
    }


@course_app.command("assignments")
@handle_errors
def course_assignments(course: CourseArg, as_json: JsonOpt = False) -> None:
    """List a course's assignments and due dates.

    For every course at once, use `courses assignments`.
    """
    with _client() as client:
        resolved = client.resolve_course(course)
        assignments = client.get_assignments([resolved.id])

    if as_json:
        _emit_json([a.model_dump(mode="json") for a in assignments])
        return

    count = len(assignments)
    table = Table(title=f"{count} {_plural(count, 'assignment')} in {escape(resolved.shortname)}")
    table.add_column("id", justify="right", style="dim")
    table.add_column("name")
    table.add_column("due", justify="right", style="dim")
    table.add_column("grade", justify="right", style="dim")
    for a in assignments:
        table.add_row(str(a.id), escape(a.name), _format_epoch(a.duedate), _grade_cell(a))
    console.print(table)


def _grade_cell(assignment: Assignment) -> str:
    """The grade column holds a point maximum, and a scale-graded assignment has none.

    Moodle encodes "graded by scale N" as a negative ``grade``; printed as a number it
    reads as a maximum of -N. The scale's name is not in this payload, so the column can
    only say which kind of grading applies.
    """
    if assignment.scale_graded:
        return "scale"
    return f"{assignment.max_grade:g}" if assignment.max_grade else "-"


AssignmentIdArg = Annotated[
    int, typer.Argument(help="Assignment id, as shown by `course assignments`.")
]


@course_app.command("assignment-status")
@handle_errors
def course_assignment_status(assignment_id: AssignmentIdArg, as_json: JsonOpt = False) -> None:
    """Show submission and grading status for one assignment.

    `assignment_id` is the id from `course assignments` — not a course-module id, which
    this call rejects.
    """
    with _client() as client:
        status = client.get_assignment_status(assignment_id)

    if as_json:
        _emit_json(status.model_dump(mode="json"))
        return

    console.print(f"submitted: {'yes' if status.submitted else 'no'} ({status.status or '-'})")
    console.print(f"graded: {'yes' if status.graded else 'no'}")
    if status.gradefordisplay:
        console.print(f"grade: {escape(status.gradefordisplay)}")
    if status.submitted_files:
        console.print("files:")
        for name in status.submitted_files:
            console.print(f"  {escape(name)}")
    if status.extensionduedate:
        console.print(f"extension until: {_format_epoch(status.extensionduedate)}")


@course_app.command("quizzes")
@handle_errors
def course_quizzes(course: CourseArg, as_json: JsonOpt = False) -> None:
    """List a course's quizzes and their open/close windows."""
    with _client() as client:
        resolved = client.resolve_course(course)
        quizzes = client.get_quizzes([resolved.id])

    if as_json:
        _emit_json([q.model_dump(mode="json") for q in quizzes])
        return

    table = Table(title=f"{len(quizzes)} quizzes in {resolved.shortname}")
    table.add_column("id", justify="right", style="dim")
    table.add_column("name")
    table.add_column("closes", justify="right", style="dim")
    table.add_column("attempts", justify="right", style="dim")
    table.add_column("max grade", justify="right", style="dim")
    for q in quizzes:
        attempts = str(q.attempts) if q.attempts else "unlimited"
        table.add_row(
            str(q.id),
            escape(q.name),
            _format_epoch(q.timeclose),
            attempts,
            str(q.grade),
        )
    console.print(table)


QuizIdArg = Annotated[int, typer.Argument(help="Quiz id, as shown by `course quizzes`.")]


@course_app.command("quiz-status")
@handle_errors
def course_quiz_status(
    quiz_id: QuizIdArg,
    course: Annotated[
        str | None,
        typer.Option("--course", help="Course the quiz belongs to. Narrows the grade lookup."),
    ] = None,
    as_json: JsonOpt = False,
) -> None:
    """Show attempt count and best grade for one quiz.

    `quiz_id` is the id from `course quizzes`. Passing `--course` keeps the maximum-grade
    lookup to that course; without it every enrolled course's quizzes are fetched, since a
    quiz id alone does not say which course holds it.
    """
    with _client() as client:
        course_id = client.resolve_course(course).id if course else None
        status = client.get_quiz_status(quiz_id, course_id=course_id)

    if as_json:
        _emit_json(status.model_dump(mode="json"))
        return

    console.print(f"attempts used: {status.attempt_count}")
    if status.last_state:
        console.print(f"last attempt: {status.last_state}")
    if status.has_grade:
        # The grade arrives already scaled to the quiz maximum, so it reads as a
        # proportion only next to that maximum.
        scale = f" / {status.max_grade}" if status.max_grade else ""
        pass_note = f" (pass: {status.grade_to_pass})" if status.grade_to_pass else ""
        console.print(f"grade: {status.grade}{scale}{pass_note}")
    else:
        # One flag covers never attempted, awaiting manual grading, and graded with the
        # marks hidden by the quiz's review options — so report availability, not grading.
        console.print("grade: not available (not graded yet, or hidden by the quiz)")


@course_app.command("grades")
@handle_errors
def course_grades(course: CourseArg, as_json: JsonOpt = False) -> None:
    """Show the per-item grade breakdown for one course: assignments, quizzes, etc.

    Fails if the instructor has not opened the gradebook to students in this course;
    `courses grades` still works in that case, just without per-item detail.
    """
    with _client() as client:
        resolved = client.resolve_course(course)
        items = client.get_grade_items(resolved.id)

    if as_json:
        _emit_json([i.model_dump(mode="json") for i in items])
        return

    table = Table(title=f"Grades for {resolved.shortname}")
    table.add_column("item")
    table.add_column("grade", justify="right")
    table.add_column("max", justify="right", style="dim")
    for i in items:
        table.add_row(escape(i.label), i.gradeformatted or "-", str(i.grademax))
    console.print(table)


def main() -> None:
    """Entry point that turns library errors into clean CLI failures."""
    try:
        app()
    except MoodleError as exc:
        err_console.print(f"[red]Error:[/red] {escape(str(exc))}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
