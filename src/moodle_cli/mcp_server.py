"""MCP server exposing the campus to an agent.

Two rules shape every signature here:

1. **No file contents cross the wire.** Downloads land on disk and the tool returns a
   manifest of paths. A course can hold tens of megabytes of PDFs; returning bytes or
   extracted text would blow up the caller's context for no benefit.
2. **Emails are opt-in.** The participants endpoint returns an address for every enrolled
   person. That is not something to place in a model's context by default.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Literal

import httpx
from mcp.server.fastmcp import FastMCP

from moodle_cli.auth import resolve_token
from moodle_cli.client import MoodleClient
from moodle_cli.config import load_config
from moodle_cli.downloads import (
    DownloadStatus,
    download_file,
    iter_course_files,
    plan_downloads,
    sanitize,
)
from moodle_cli.errors import MoodleError
from moodle_cli.models import html_to_text
from moodle_cli.search import search_contents

View = Literal["all", "all-including-hidden", "in-progress", "future", "past", "starred", "hidden"]
Sort = Literal["name", "last-accessed"]

mcp = FastMCP("moodle-campus")


def _open_client() -> tuple[MoodleClient, str]:
    config = load_config()
    token = resolve_token(config)
    return MoodleClient(config.base_url, token), token


def _course_names(client: MoodleClient) -> dict[int, str]:
    """Shortname per course id, for labelling rows that carry only an id.

    Includes courses hidden from the dashboard: the grade and assignment endpoints answer
    for every enrolment, so anything narrower leaves a bare id in the output.
    """
    return {c.id: c.shortname for c in client.list_courses(view="all-including-hidden")}


@mcp.tool()
def list_courses(view: View = "all", sort: Sort = "name") -> list[dict[str, Any]]:
    """List the enrolled courses.

    Note: this campus never sets course end dates, so the time-based views are not
    meaningful here. 'in-progress' returns every course and 'past'/'future' return none.
    Use 'all' or 'starred', and read the start date to judge recency.
    """
    client, _ = _open_client()
    with client:
        return [
            {
                "id": c.id,
                "shortname": c.shortname,
                "fullname": c.fullname,
                "category": c.category,
                "starred": c.isfavourite,
                "start_date": c.started_at.date().isoformat() if c.started_at else None,
                "url": c.viewurl,
            }
            for c in client.list_courses(view=view, sort=sort)
        ]


@mcp.tool()
def get_course_contents(course: str) -> dict[str, Any]:
    """Show a course's sections, activities, available files and external links.

    `course` accepts a numeric id or a shortname prefix such as "IOS460".
    File entries list names, sizes and MIME types; to fetch them, call
    download_course_files, optionally narrowing by section number or module type.
    Link entries (a "url" module's actual destination, e.g. a recorded-class or
    external-site link) are informational only — nothing downloads them.
    """
    client, _ = _open_client()
    with client:
        resolved = client.resolve_course(course)
        sections = client.get_course_contents(resolved.id)

    return {
        "course": {
            "id": resolved.id,
            "shortname": resolved.shortname,
            "fullname": resolved.fullname,
        },
        "sections": [
            {
                "number": section.section,
                "name": section.name,
                "modules": [
                    {
                        "name": module.name,
                        "type": module.modname,
                        "url": module.url,
                        "files": [
                            {"filename": f.filename, "size": f.filesize, "mimetype": f.mimetype}
                            for f in module.files
                        ],
                        "links": [
                            {"name": link.filename, "url": link.fileurl} for link in module.links
                        ],
                    }
                    for module in section.modules
                ],
            }
            for section in sections
        ],
    }


@mcp.tool()
def search_courses(query: str) -> dict[str, Any]:
    """Search section, activity, file and link names across every enrolled course.

    Case-insensitive substring match on names and on link destinations — it does not read
    file contents. One call here replaces one get_course_contents call per course, which
    matters when the question is "which course has X" rather than "what's in course X".

    Every record names what the query hit under `match`: "section", "module", "file" or
    "link". A "section" record carries no module fields. On a "module" hit, `files` and
    `links` are the activity's complete contents; on a "file" or "link" hit they hold only
    the entries that matched, so an empty list never means "this activity is empty".
    `section_number` feeds download_course_files' `sections` selector directly.

    `truncated` is true when more matched than the response carries: narrow the query.
    """
    client, _ = _open_client()
    with client:
        return search_contents(client, query).as_payload()


@mcp.tool()
def download_course_files(
    course: str,
    output_dir: str | None = None,
    sections: list[int] | None = None,
    module_types: list[str] | None = None,
    files: list[str] | None = None,
    match: list[str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Download a course's files to disk, mirroring its section structure.

    Returns a manifest of file paths and sizes, never file contents. Read the downloaded
    files afterwards with normal filesystem tools if their contents are needed.

    Selectors narrow what is fetched and compose by intersection: `sections` and
    `module_types` by structure, `files` and `match` by filename. `files` holds exact
    filenames as returned by get_course_contents; a name that matches nothing is an error,
    so a wrong name fails instead of silently downloading nothing. `match` holds
    case-insensitive globs such as "*.pdf".

    `output_dir` defaults to ./<course shortname>/. Set `dry_run` to preview the plan.
    """
    config = load_config()
    token = resolve_token(config)

    with MoodleClient(config.base_url, token) as client:
        resolved = client.resolve_course(course)
        contents = client.get_course_contents(resolved.id)

    root = (
        Path(output_dir)
        if output_dir
        else Path(sanitize(resolved.shortname, fallback=str(resolved.id)))
    )
    planned = plan_downloads(
        contents,
        root,
        only_sections=set(sections) if sections else None,
        only_modtypes=set(module_types) if module_types else None,
        only_names=set(files) if files else None,
        only_patterns=match or None,
    )

    if files:
        selected = {p.file.filename for p in planned}
        unknown = [name for name in files if name not in selected]
        if unknown:
            in_course = {f.filename for _, _, f in iter_course_files(contents)}

            def reason(name: str) -> str:
                return "excluded by another selector" if name in in_course else "not in this course"

            detail = ", ".join(f"{name!r} ({reason(name)})" for name in unknown)
            raise ValueError(f"No such file: {detail}")

    manifest: list[dict[str, Any]] = []
    if dry_run:
        for item in planned:
            manifest.append(
                {
                    "path": str(item.destination),
                    "size": item.file.filesize,
                    "module_type": item.module.modname,
                    "status": "planned",
                }
            )
        return {
            "course": resolved.shortname,
            "directory": str(root),
            "dry_run": True,
            "files": manifest,
        }

    downloaded = skipped = failed = 0
    with httpx.Client(timeout=300, follow_redirects=True) as http:
        for item in planned:
            entry: dict[str, Any] = {
                "path": str(item.destination),
                "size": item.file.filesize,
                "module_type": item.module.modname,
            }
            try:
                result = download_file(http, item.file, token, item.destination)
            except MoodleError as exc:
                failed += 1
                entry.update(status="failed", error=str(exc))
            else:
                if result.status is DownloadStatus.SKIPPED:
                    skipped += 1
                else:
                    downloaded += 1
                entry.update(status=result.status.value, size=result.size)
            manifest.append(entry)

    return {
        "course": resolved.shortname,
        "directory": str(root),
        "summary": {"downloaded": downloaded, "already_present": skipped, "failed": failed},
        "files": manifest,
    }


@mcp.tool()
def list_participants(
    course: str,
    role: str | None = None,
    include_emails: bool = False,
) -> list[dict[str, Any]]:
    """List the people enrolled in a course.

    Email addresses are omitted unless `include_emails` is true. Only set it when the task
    actually requires contacting someone; otherwise leave these out of context.

    `role` filters by role shortname, e.g. "student" or "editingteacher".
    """
    client, _ = _open_client()
    with client:
        resolved = client.resolve_course(course)
        participants = client.get_participants(resolved.id)

    if role:
        needle = role.casefold()
        participants = [p for p in participants if needle in {r.casefold() for r in p.role_names}]

    people: list[dict[str, Any]] = []
    for person in participants:
        entry: dict[str, Any] = {
            "id": person.id,
            "fullname": person.fullname,
            "roles": person.role_names,
            "last_course_access": (
                person.last_course_access.date().isoformat() if person.last_course_access else None
            ),
        }
        if include_emails:
            entry["email"] = person.email
        people.append(entry)
    return people


@mcp.tool()
def get_course_announcements(course: str | None = None) -> list[dict[str, Any]]:
    """List announcements from a course's news forum, newest first.

    `course` accepts a numeric id or a shortname prefix; omit it to check every enrolled
    course, dashboard-hidden ones included. Only a forum Moodle marks as "news" carries
    announcements — a course's regular discussion forums are not included, and a course
    without a news forum returns nothing. `message` is plain text; `posted_at` keeps the
    time of day, which is what tells two posts of the same day apart.
    """
    client, _ = _open_client()
    with client:
        # The course list is fetched once and reused as both the sweep's scope and its
        # id -> shortname map; letting get_announcements enumerate again would double the
        # round trip on the default path.
        courses = (
            [client.resolve_course(course)]
            if course
            else client.list_courses(view="all-including-hidden")
        )
        names = {c.id: c.shortname for c in courses}
        announcements = client.get_announcements([c.id for c in courses])

    return [
        {
            "id": a.id,
            "course": names.get(a.courseid, str(a.courseid)),
            "subject": a.subject,
            "message": a.message_text,
            "author": a.userfullname,
            "posted_at": a.posted_at.isoformat() if a.posted_at else None,
            "replies": a.numreplies,
            "pinned": a.pinned,
        }
        for a in announcements
    ]


@mcp.tool()
def get_grade_summary() -> list[dict[str, Any]]:
    """Course-level grade summary across every enrolled course.

    Works even for a course whose gradebook is not open to students. For a per-item
    breakdown of one course — individual assignments, quizzes, etc. — use get_grades.
    """
    client, _ = _open_client()
    with client:
        course_names = _course_names(client)
        overview = client.get_grade_overview()

    return [
        {"course": course_names.get(g.courseid, str(g.courseid)), "grade": g.grade}
        for g in overview
    ]


@mcp.tool()
def get_grades(course: str) -> list[dict[str, Any]]:
    """Per-item grade breakdown for one course: assignments, quizzes, etc.

    Raises if the instructor has not opened the gradebook to students in this course;
    get_grade_summary still works in that case, just without the per-item detail.

    Aggregate rows are included: `item` reads "Course total" or "Category subtotal" for the
    rows Moodle sends unnamed.
    """
    client, _ = _open_client()
    with client:
        resolved = client.resolve_course(course)
        items = client.get_grade_items(resolved.id)

    return [
        {
            "item": item.label,
            "grade": item.gradeformatted,
            "max": item.grademax,
            "percentage": item.percentageformatted,
            "feedback": html_to_text(item.feedback),
        }
        for item in items
    ]


def main() -> None:
    """Run the server over stdio."""
    # httpx logs every request at INFO, which buries real server diagnostics on stderr.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    mcp.run()


if __name__ == "__main__":
    main()
