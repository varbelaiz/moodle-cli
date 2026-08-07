"""Cross-course search tests, driven through the HTTP layer.

The fixture serves the same course contents to all 3 enrolled courses, so a per-course
rule shows up as three identical hits.
"""

from __future__ import annotations

from typing import Any

import pytest
import respx

from moodle_cli.client import MoodleClient
from moodle_cli.search import MatchKind, search_contents
from tests.conftest import BASE_URL, route_by_function


@pytest.fixture
def client() -> MoodleClient:
    return MoodleClient(BASE_URL, "test-token")


@respx.mock
def test_the_sweep_includes_courses_hidden_from_the_dashboard(
    client: MoodleClient, courses_payload: dict[str, Any], contents_payload: list[dict[str, Any]]
) -> None:
    """Hiding a course on the dashboard is a display choice, not a search exclusion."""
    route = route_by_function(
        core_course_get_enrolled_courses_by_timeline_classification=courses_payload,
        core_course_get_contents=contents_payload,
    )

    search_contents(client, "slack")

    assert "classification=allincludinghidden" in route.calls[0].request.content.decode()


@respx.mock
def test_a_module_name_hit_carries_the_modules_whole_contents(
    client: MoodleClient, courses_payload: dict[str, Any], contents_payload: list[dict[str, Any]]
) -> None:
    """An activity matched by name reports every file it holds, not the ones named like it."""
    route_by_function(
        core_course_get_enrolled_courses_by_timeline_classification=courses_payload,
        core_course_get_contents=contents_payload,
    )

    hits = search_contents(client, "Material Bibliogr").hits

    assert {hit.kind for hit in hits} == {MatchKind.MODULE}
    assert all(
        [f.filename for f in hit.files] == ["_Carátula licencia.pdf", "Cap 1.pdf"] for hit in hits
    )


@respx.mock
def test_a_file_hit_carries_only_the_matching_files(
    client: MoodleClient, courses_payload: dict[str, Any], contents_payload: list[dict[str, Any]]
) -> None:
    route_by_function(
        core_course_get_enrolled_courses_by_timeline_classification=courses_payload,
        core_course_get_contents=contents_payload,
    )

    hits = search_contents(client, "Cap 1").hits

    assert {hit.kind for hit in hits} == {MatchKind.FILE}
    assert all([f.filename for f in hit.files] == ["Cap 1.pdf"] for hit in hits)


@respx.mock
def test_a_link_matches_on_its_destination_as_well_as_its_label(
    client: MoodleClient, courses_payload: dict[str, Any], contents_payload: list[dict[str, Any]]
) -> None:
    """A link's service is often named only in its URL."""
    route_by_function(
        core_course_get_enrolled_courses_by_timeline_classification=courses_payload,
        core_course_get_contents=contents_payload,
    )

    hits = search_contents(client, "slack.example.com").hits

    assert {hit.kind for hit in hits} == {MatchKind.LINK}
    assert all(
        [link.fileurl for link in hit.links] == ["https://slack.example.com/join"] for hit in hits
    )


@respx.mock
def test_a_hit_carries_the_section_number_a_download_selects_by(
    client: MoodleClient, courses_payload: dict[str, Any], contents_payload: list[dict[str, Any]]
) -> None:
    route_by_function(
        core_course_get_enrolled_courses_by_timeline_classification=courses_payload,
        core_course_get_contents=contents_payload,
    )

    hits = search_contents(client, "Trabajo Final").hits

    assert hits
    assert all(hit.section_number == 1 for hit in hits)


@respx.mock
def test_results_past_the_cap_are_dropped_and_flagged_truncated(
    client: MoodleClient, courses_payload: dict[str, Any], contents_payload: list[dict[str, Any]]
) -> None:
    """A flooding query is answered with a cap and a flag, never a silently full-looking list."""
    route = route_by_function(
        core_course_get_enrolled_courses_by_timeline_classification=courses_payload,
        core_course_get_contents=contents_payload,
    )

    results = search_contents(client, "a", limit=1)

    assert results.truncated is True
    assert len(results.hits) == 1
    # The sweep stops at the first course past the cap: one course listing, one contents call.
    assert len(route.calls) == 2
