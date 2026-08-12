"""Fetching one course file and converting it to markdown.

Goes through the same machinery `course download` uses -- plan_downloads,
download_file -- so a file already on disk at the expected size is reused rather than
re-fetched, and a truncated or bogus response is rejected the same way `course download`
rejects one.
"""

from __future__ import annotations

from pathlib import Path

import httpx

from moodle_cli.downloads import download_file, plan_downloads, sanitize
from moodle_cli.session import open_client
from moodle_cli_anydoc.convert import Converted, convert_file


def fetch_and_convert(course: str, filename: str, *, section: int | None = None) -> Converted:
    """Resolve COURSE, fetch FILENAME, and convert what was fetched to markdown.

    Raises ValueError if no file in the course matches FILENAME, or if more than one
    does -- this campus has courses where a duplicated activity produces two files under
    the same name with different sizes, and `section` is how a caller tells them apart.
    """
    with open_client() as client:
        token = client.token
        resolved = client.resolve_course(course)
        contents = client.get_course_contents(resolved.id)

    root = Path(sanitize(resolved.shortname, fallback=str(resolved.id)))
    planned = plan_downloads(
        contents,
        root,
        only_names={filename},
        only_sections={section} if section is not None else None,
    )
    if not planned:
        raise ValueError(f"{filename!r}: no such file in {resolved.shortname}")
    if len(planned) > 1:
        sections = sorted({item.section.section for item in planned})
        if len(sections) > 1:
            raise ValueError(
                f"{filename!r} matches {len(planned)} files in {resolved.shortname} "
                f"across sections {sections}; narrow with section"
            )
        # One section holds them all, so `section` has nothing left to narrow: two
        # activities in it carry the same filename at different sizes, which is what
        # `course download` handles by keeping both under distinct names. Sending the
        # caller back to `section` would hand them this same error again.
        activities = ", ".join(
            f"{item.module.name!r} ({item.file.filesize} bytes)" for item in planned
        )
        raise ValueError(
            f"{filename!r} matches {len(planned)} files in section {sections[0]} of "
            f"{resolved.shortname}, from {activities}. Section cannot tell them apart; "
            f'fetch them with `moodle course download {resolved.shortname} --file "{filename}"` '
            f"and convert them with `moodle anydoc convert`."
        )

    item = planned[0]
    with httpx.Client(timeout=300, follow_redirects=True) as http:
        download_file(http, item.file, token, item.destination)

    return convert_file(item.destination)
