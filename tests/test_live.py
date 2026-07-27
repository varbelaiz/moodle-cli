"""Integration tests against the real campus.

Skipped unless ``--live`` is passed. These exist to catch the campus changing its API in a
way the recorded fixtures cannot: the mocked suite proves the code is self-consistent, this
proves the assumptions still hold upstream.

Requires MOODLE_URL plus either a stored token, MOODLE_TOKEN, or MOODLE_USER/MOODLE_PASS.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from moodle_cli.auth import resolve_token
from moodle_cli.client import MoodleClient
from moodle_cli.config import load_config
from moodle_cli.downloads import download_file, plan_downloads

pytestmark = pytest.mark.live

MAX_SMOKE_DOWNLOAD_BYTES = 2_000_000


@pytest.fixture(scope="module")
def live_client() -> MoodleClient:
    config = load_config()
    return MoodleClient(config.base_url, resolve_token(config))


@pytest.fixture(scope="module")
def live_token() -> str:
    return resolve_token(load_config())


def test_site_info_reports_web_services_and_downloads(live_client: MoodleClient) -> None:
    info = live_client.get_site_info()
    assert info.userid > 0
    assert info.downloadfiles, "file downloads are disabled for this token"
    # The four functions the tool is built on must stay exposed by the mobile service.
    assert {
        "core_webservice_get_site_info",
        "core_course_get_enrolled_courses_by_timeline_classification",
        "core_course_get_contents",
        "core_enrol_get_enrolled_users",
    } <= info.function_names


def test_every_view_and_sort_combination_is_accepted(live_client: MoodleClient) -> None:
    from moodle_cli.client import SORTS, VIEWS

    for view in VIEWS:
        for sort in SORTS:
            live_client.list_courses(view=view, sort=sort)  # must not raise


def test_starred_is_a_strict_subset_of_all(live_client: MoodleClient) -> None:
    all_ids = {c.id for c in live_client.list_courses(view="all")}
    starred = live_client.list_courses(view="starred")
    assert starred, "expected at least one starred course"
    assert {c.id for c in starred} <= all_ids


def test_course_contents_and_participants_round_trip(live_client: MoodleClient) -> None:
    course = live_client.list_courses(view="starred", sort="last-accessed")[0]

    sections = live_client.get_course_contents(course.id)
    assert sections

    participants = live_client.get_participants(course.id)
    assert participants
    assert all(p.id > 0 and p.fullname for p in participants)


def test_downloading_a_real_file_matches_the_declared_size(
    live_client: MoodleClient, live_token: str, tmp_path: Path
) -> None:
    """The size check is the whole point: a JSON error body would not match filesize."""
    for course in live_client.list_courses(view="starred", sort="last-accessed"):
        planned = plan_downloads(live_client.get_course_contents(course.id), tmp_path)
        candidates = [p for p in planned if 0 < p.file.filesize <= MAX_SMOKE_DOWNLOAD_BYTES]
        if not candidates:
            continue

        target = candidates[0]
        with httpx.Client(timeout=120, follow_redirects=True) as http:
            result = download_file(http, target.file, live_token, target.destination)

        assert result.size == target.file.filesize
        assert target.destination.stat().st_size == target.file.filesize
        return

    pytest.skip("no starred course exposes a small enough file to smoke-test")
