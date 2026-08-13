"""Integration tests against the real Panopto integration.

Skipped unless ``--live`` is passed. Discovers a course with recordings dynamically --
nothing here hardcodes a course, a delivery id, or a language code, since those are
this campus's own data, not an assumption to encode.

Requires MOODLE_URL plus MOODLE_USER/MOODLE_PASS -- a bare MOODLE_TOKEN cannot reach
the Panopto integration (see moodle_cli_panopto.fetch.open_context).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from moodle_cli_panopto.errors import PanoptoError
from moodle_cli_panopto.fetch import get_transcript, list_course_recordings
from moodle_cli_panopto.recordings import Recording

from moodle_cli.session import open_client

pytestmark = pytest.mark.live

_TIMESTAMP_MARKER = re.compile(r"\*\*\d{2}:\d{2}:\d{2}\*\*")


def _first_course_with_recordings() -> tuple[str, list[Recording]] | None:
    """A course shortname and its recordings, for the first enrolled course with any."""
    with open_client() as client:
        courses = client.list_courses(view="all")
    for course in courses:
        try:
            _resolved, recordings = list_course_recordings(course.shortname)
        except PanoptoError:
            continue
        if recordings:
            return course.shortname, recordings
    return None


def test_list_and_transcribe_a_real_recording(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Round-trips the whole chain: block listing, LTI relay, DeliveryInfo, GenerateSRT.

    Runs from a scratch directory outside the repo -- real transcript content must
    never land in the working tree, live suite included.
    """
    monkeypatch.chdir(tmp_path)
    found = _first_course_with_recordings()
    if found is None:
        pytest.skip("no enrolled course currently has a Panopto recording")
    course, recordings = found

    recording = recordings[0]
    assert recording.id
    assert recording.name

    content = get_transcript(course, recording.id)

    assert content.markdown.strip()
    assert _TIMESTAMP_MARKER.search(content.markdown), "expected at least one **HH:MM:SS** marker"
    assert list(tmp_path.rglob("*")) == [], "get_transcript must not write to disk"
