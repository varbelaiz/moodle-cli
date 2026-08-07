"""MCP tool tests.

Individual Moodle calls are already covered by test_client.py and the search sweep by
test_search.py; these exercise the payload the tools hand to an agent.
"""

from __future__ import annotations

import itertools
from typing import Any

import httpx
import pytest
import respx

from moodle_cli.errors import MoodleAPIError
from moodle_cli.mcp_server import search_courses
from tests.conftest import REST_URL, route_by_function

pytestmark = pytest.mark.usefixtures("configured_env")


# -- search_courses ----------------------------------------------------------------


@respx.mock
def test_search_courses_matches_module_and_link_names(
    courses_payload: dict[str, Any], contents_payload: list[dict[str, Any]]
) -> None:
    route_by_function(
        core_course_get_enrolled_courses_by_timeline_classification=courses_payload,
        core_course_get_contents=contents_payload,
    )

    results = search_courses("slack")["results"]

    # contents_payload is served identically to all 3 enrolled courses in this fixture.
    assert len(results) == 3
    assert all(r["module"] == "Slack de la Materia" for r in results)
    assert all(
        r["links"] == [{"name": "Slack de la Materia", "url": "https://slack.example.com/join"}]
        for r in results
    )
    # A url module's target is never reported under `files`.
    assert all(r["files"] == [] for r in results)


@respx.mock
def test_search_courses_matches_section_names(
    courses_payload: dict[str, Any], contents_payload: list[dict[str, Any]]
) -> None:
    route_by_function(
        core_course_get_enrolled_courses_by_timeline_classification=courses_payload,
        core_course_get_contents=contents_payload,
    )

    results = search_courses("entregas")["results"]

    assert results
    assert all(r["match"] == "section" for r in results)
    assert all(r["section_number"] == 1 for r in results)
    assert {r["course"] for r in results} == {"IOS460 - 123246", "I312 - 106931", "I310 - 106934"}


@respx.mock
def test_every_record_names_what_the_query_matched(
    courses_payload: dict[str, Any], contents_payload: list[dict[str, Any]]
) -> None:
    """A caller iterating results branches on `match`, so it is on every record shape."""
    route_by_function(
        core_course_get_enrolled_courses_by_timeline_classification=courses_payload,
        core_course_get_contents=contents_payload,
    )

    results = search_courses("a")["results"]

    assert results
    assert {r["match"] for r in results} <= {"section", "module", "file", "link"}
    assert all("section_number" in r for r in results)


@respx.mock
def test_search_courses_is_case_insensitive_and_strips_the_query(
    courses_payload: dict[str, Any], contents_payload: list[dict[str, Any]]
) -> None:
    route_by_function(
        core_course_get_enrolled_courses_by_timeline_classification=courses_payload,
        core_course_get_contents=contents_payload,
    )

    assert search_courses("  SLACK  ") == search_courses("slack")


@respx.mock
def test_search_courses_returns_empty_for_a_blank_query() -> None:
    """A blank needle matches every name, so it must not reach the network at all."""
    route = route_by_function(core_course_get_enrolled_courses_by_timeline_classification={})

    assert search_courses("   ") == {"results": [], "truncated": False}
    assert not route.called


@respx.mock
def test_search_aborts_on_an_error_body_from_any_course_in_the_sweep(
    courses_payload: dict[str, Any], contents_payload: list[dict[str, Any]]
) -> None:
    """Half a sweep is not a result: an error payload cannot read as "no match here"."""
    contents_calls = itertools.count()

    def responder(request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        if "wsfunction=core_course_get_contents" not in body:
            return httpx.Response(200, json=courses_payload)
        if next(contents_calls) == 0:
            return httpx.Response(200, json=contents_payload)
        return httpx.Response(
            200,
            json={
                "exception": "moodle_exception",
                "errorcode": "nopermissions",
                "message": "Sorry, but you do not currently have permissions to do that",
            },
        )

    respx.post(REST_URL).mock(side_effect=responder)

    with pytest.raises(MoodleAPIError):
        search_courses("slack")
