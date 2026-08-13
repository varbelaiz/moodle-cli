"""Listing a course's Panopto recordings, and resolving one (or several) by name or id.

``block_panopto_get_content`` is not part of the REST web-service surface -- it is the
internal AJAX call the course page itself makes to render its Panopto block -- so the
answer is a rendered HTML fragment, not a JSON structure, and has to be scraped.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, urlparse

from moodle_cli.downloads import matches_selection
from moodle_cli_panopto.errors import PanoptoError
from moodle_cli_panopto.moodle_login import MoodleWebSession

_AJAX_PATH = "/lib/ajax/service.php"
_VIEWER_PATH_MARKER = "/Panopto/Pages/Viewer.aspx"


@dataclass(frozen=True)
class Recording:
    id: str
    """The Panopto delivery id -- what ``DeliveryInfo.aspx``/``GenerateSRT.ashx`` key on."""
    name: str
    host: str
    """The Panopto host this recording is served from, e.g. ``campus.hosted.panopto.com``."""


class _RecordingLinkParser(HTMLParser):
    """Pulls every ``<a href="...Viewer.aspx?id=...">name</a>`` out of the block's fragment.

    A real parser rather than a regex because the anchor text can legitimately contain
    nested markup (Panopto has wrapped it in a ``<span>`` on other campuses), which a
    non-greedy regex would truncate at the first inner closing tag.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.recordings: list[Recording] = []
        self._current_url: str | None = None
        self._buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href")
        if href and _VIEWER_PATH_MARKER in href:
            self._current_url = href
            self._buffer = []

    def handle_data(self, data: str) -> None:
        if self._current_url is not None:
            self._buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or self._current_url is None:
            return
        parsed = urlparse(self._current_url)
        delivery_id = parse_qs(parsed.query).get("id", [None])[0]
        if delivery_id:
            name = " ".join("".join(self._buffer).split())
            self.recordings.append(
                Recording(id=delivery_id, name=name or delivery_id, host=parsed.netloc)
            )
        self._current_url = None
        self._buffer = []


def _parse_recordings(fragment: str) -> list[Recording]:
    parser = _RecordingLinkParser()
    parser.feed(fragment)
    return parser.recordings


def list_recordings(moodle: MoodleWebSession, course_id: int) -> list[Recording]:
    """List COURSE_ID's Panopto recordings via the course's own Panopto block.

    Cheap and course-scoped: this never reaches a Panopto host, only Moodle's internal
    AJAX endpoint. A live-in-progress session is listed the same as a completed one --
    its transcript, if requested, fails cleanly later rather than being filtered here.
    """
    response = moodle.client.post(
        _AJAX_PATH,
        params={"sesskey": moodle.sesskey, "info": "block_panopto_get_content"},
        json=[
            {
                "index": 0,
                "methodname": "block_panopto_get_content",
                "args": {"courseid": course_id},
            }
        ],
    )
    response.raise_for_status()
    try:
        body: Any = response.json()
    except ValueError as exc:
        raise PanoptoError(
            f"course {course_id}: block_panopto_get_content returned a non-JSON response"
        ) from exc

    if not isinstance(body, list) or not body or not isinstance(body[0], dict):
        raise PanoptoError(
            f"course {course_id}: block_panopto_get_content returned an unexpected response"
        )

    entry = body[0]
    if entry.get("error"):
        exception = entry.get("exception")
        message = exception.get("message") if isinstance(exception, dict) else None
        detail = f": {message}" if message else ""
        raise PanoptoError(f"course {course_id}: block_panopto_get_content failed{detail}")

    return _parse_recordings(str(entry.get("data") or ""))


def resolve_session(recordings: list[Recording], selector: str) -> Recording:
    """Resolve SELECTOR to exactly one recording: an exact delivery id, else an exact
    display name, else a case-insensitive name substring.

    Raises ValueError on zero or on two-or-more matches, naming what matched -- the same
    disambiguation style as ``MoodleClient.resolve_course``.
    """
    for recording in recordings:
        if recording.id == selector:
            return recording
    for recording in recordings:
        if recording.name == selector:
            return recording

    needle = selector.casefold()
    matches = [r for r in recordings if needle in r.name.casefold()]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise ValueError(f"{selector!r}: no recording matches")
    names = ", ".join(sorted(r.name for r in matches))
    raise ValueError(f"{selector!r} is ambiguous; matches: {names}")


def select_sessions(
    recordings: list[Recording],
    names: Collection[str] | None,
    patterns: Collection[str] | None,
) -> list[Recording]:
    """Batch filter for ``download --session``/``--match``.

    A ``names`` entry matches either a recording's exact delivery id or its exact
    display name; ``patterns`` globs against the display name. Union semantics, no
    disambiguation error -- a batch command matching several recordings is the point.
    With neither given, every recording is selected.
    """
    if names is None and patterns is None:
        return list(recordings)
    ids = set(names or ())
    return [r for r in recordings if r.id in ids or matches_selection(r.name, names, patterns)]


__all__ = ["Recording", "list_recordings", "resolve_session", "select_sessions"]
