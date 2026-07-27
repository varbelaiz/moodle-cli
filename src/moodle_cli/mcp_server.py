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
from moodle_cli.downloads import DownloadStatus, download_file, plan_downloads, sanitize
from moodle_cli.errors import MoodleError

View = Literal["all", "all-including-hidden", "in-progress", "future", "past", "starred", "hidden"]
Sort = Literal["name", "last-accessed"]

mcp = FastMCP("moodle-campus")


def _open_client() -> tuple[MoodleClient, str]:
    config = load_config()
    token = resolve_token(config)
    return MoodleClient(config.base_url, token), token


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
    """Show a course's sections, activities and available files.

    `course` accepts a numeric id or a shortname prefix such as "IOS460".
    File entries list names, sizes and MIME types. To fetch them, call
    download_course_files, optionally narrowing by section number or module type.
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
                    }
                    for module in section.modules
                ],
            }
            for section in sections
        ],
    }


@mcp.tool()
def download_course_files(
    course: str,
    output_dir: str | None = None,
    section: int | None = None,
    module_type: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Download a course's files to disk, mirroring its section structure.

    Returns a manifest of file paths and sizes, never file contents. Read the downloaded
    files afterwards with normal filesystem tools if their contents are needed.

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
        only_sections={section} if section is not None else None,
        only_modtypes={module_type} if module_type else None,
    )

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


def main() -> None:
    """Run the server over stdio."""
    # httpx logs every request at INFO, which buries real server diagnostics on stderr.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    mcp.run()


if __name__ == "__main__":
    main()
