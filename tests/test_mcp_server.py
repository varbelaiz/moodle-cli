"""MCP tool tests.

Individual Moodle calls are already covered by test_client.py and the search sweep by
test_search.py; these exercise the payload the tools hand to an agent.
"""

from __future__ import annotations

import itertools
import json
from typing import Any

import httpx
import pytest
import respx
from typer.testing import CliRunner

from moodle_cli.cli import app
from moodle_cli.errors import MoodleAPIError
from moodle_cli.mcp_server import get_course_announcements, search_courses
from tests.conftest import REST_URL, posted_params, route_by_function

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


# -- get_course_announcements -------------------------------------------------------


@respx.mock
def test_get_course_announcements_resolves_course_and_strips_html(
    courses_payload: dict[str, Any],
    forums_payload: list[dict[str, Any]],
    discussions_payload: dict[str, Any],
) -> None:
    route_by_function(
        core_course_get_enrolled_courses_by_timeline_classification=courses_payload,
        mod_forum_get_forums_by_courses=forums_payload,
        mod_forum_get_forum_discussions=discussions_payload,
    )

    results = get_course_announcements("IOS460")

    assert len(results) == 2
    assert results[0]["course"] == "IOS460 - 123246"
    assert results[0]["subject"] == "Cambio de aula para la clase del jueves"
    assert "<p>" not in results[0]["message"]
    assert "S004" in results[0]["message"]
    assert results[0]["pinned"] is True


@respx.mock
def test_get_course_announcements_sweeps_every_course_with_one_course_lookup(
    courses_payload: dict[str, Any],
    forums_payload: list[dict[str, Any]],
    discussions_payload: dict[str, Any],
) -> None:
    """The default sweep reaches dashboard-hidden courses and lists them only once."""
    route = route_by_function(
        core_course_get_enrolled_courses_by_timeline_classification=courses_payload,
        mod_forum_get_forums_by_courses=forums_payload,
        mod_forum_get_forum_discussions=discussions_payload,
    )

    results = get_course_announcements()

    functions = [posted_params(call.request)["wsfunction"] for call in route.calls]
    assert functions.count("core_course_get_enrolled_courses_by_timeline_classification") == 1
    assert posted_params(route.calls[0].request)["classification"] == "allincludinghidden"
    assert posted_params(route.calls[1].request)["courseids[2]"] == "103"
    assert {r["course"] for r in results} == {"IOS460 - 123246"}


@respx.mock
def test_get_course_announcements_names_a_post_by_course_id_when_the_course_is_unknown(
    courses_payload: dict[str, Any],
    discussions_payload: dict[str, Any],
) -> None:
    """A bare id beats dropping the post: the agent still knows two posts differ."""
    route_by_function(
        core_course_get_enrolled_courses_by_timeline_classification=courses_payload,
        mod_forum_get_forums_by_courses=[{"id": 599, "course": 404, "type": "news"}],
        mod_forum_get_forum_discussions=discussions_payload,
    )

    results = get_course_announcements()

    assert {r["course"] for r in results} == {"404"}


@respx.mock
def test_get_course_announcements_matches_the_cli_json_field_for_field(
    courses_payload: dict[str, Any],
    forums_payload: list[dict[str, Any]],
    discussions_payload: dict[str, Any],
) -> None:
    """One key, one meaning: `message` is plain text and `posted_at` local on both."""
    route_by_function(
        core_course_get_enrolled_courses_by_timeline_classification=courses_payload,
        mod_forum_get_forums_by_courses=forums_payload,
        mod_forum_get_forum_discussions=discussions_payload,
    )

    from_tool = get_course_announcements("IOS460")
    result = CliRunner().invoke(app, ["course", "announcements", "IOS460", "--json"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == from_tool
