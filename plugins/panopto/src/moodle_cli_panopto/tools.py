"""The MCP-facing tools, registered as `panopto_list_recordings`,
`panopto_download_transcript` and `panopto_get_transcript`.

Split by what each is for, mirroring `moodle_cli_anydoc`: `download_transcript`
persists to disk and returns paths only, for building up a course's recordings (a
vault, an archive); `get_transcript` reaches the campus for one named session and
returns its markdown inline, so reading one class takes one call.
"""

from __future__ import annotations

from typing import Any

from moodle_cli_panopto.fetch import (
    download_transcripts,
    get_transcript_and_save,
    list_course_recordings,
)
from moodle_cli_panopto.recordings import resolve_session

INLINE_LIMIT = 20_000


def list_recordings(course: str) -> list[dict[str, Any]]:
    """List a course's Panopto recordings: delivery id and display name.

    `course` accepts a numeric id or a shortname prefix, resolved the same way every
    other course-scoped tool does. Never reaches a Panopto host.
    """
    _resolved, recordings = list_course_recordings(course)
    return [{"id": r.id, "name": r.name} for r in recordings]


def download_transcript(course: str, session: str | None = None) -> list[dict[str, Any]]:
    """Fetch and write transcripts for a course's recordings, returning only their paths.

    `session` narrows to one recording (an exact delivery id or a name substring,
    erroring on ambiguity); omitted, every recording in the course is fetched. Content
    is never returned inline here -- for that, see `get_transcript`.
    """
    resolved, recordings = list_course_recordings(course)
    selected = [resolve_session(recordings, session)] if session is not None else recordings

    results: list[dict[str, Any]] = []
    for outcome in download_transcripts(resolved, selected):
        entry: dict[str, Any] = {
            "id": outcome.recording.id,
            "name": outcome.recording.name,
            "status": outcome.status,
            "path": str(outcome.destination) if outcome.destination else None,
        }
        if outcome.error:
            entry["error"] = outcome.error
        results.append(entry)
    return results


def get_transcript(course: str, session: str, language: int | None = None) -> dict[str, Any]:
    """Fetch one session's transcript, writing it to disk and returning it inline.

    `session` accepts an exact delivery id or a name substring, erroring on ambiguity.
    `language` overrides the caption language; by default it is read from the
    recording's own available captions, never guessed among more than one.

    Writes `markdown_path` and always returns that full path; `markdown` is capped at
    20,000 characters, with `truncated` true when the transcript runs longer -- read
    the rest from `markdown_path` directly.
    """
    result = get_transcript_and_save(course, session, language=language)
    markdown = result.markdown
    truncated = len(markdown) > INLINE_LIMIT
    return {
        "markdown_path": str(result.markdown_path),
        "markdown": markdown[:INLINE_LIMIT] if truncated else markdown,
        "truncated": truncated,
    }


__all__ = ["download_transcript", "get_transcript", "list_recordings"]
