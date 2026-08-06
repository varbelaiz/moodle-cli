"""MCP tool tests.

Individual Moodle calls are already covered by test_client.py; these exercise the
filtering/aggregation logic that lives only in the tool functions themselves.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from moodle_cli.errors import MoodleAPIError
from moodle_cli.mcp_server import (
    get_assignment_status,
    get_assignments,
    get_course_announcements,
    get_grade_summary,
    get_grades,
    get_quiz_status,
    get_quizzes,
    search_courses,
)
from tests.conftest import BASE_URL, REST_URL


@pytest.fixture(autouse=True)
def configured_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """A token in the environment keeps the tools off the keyring and off login/token.php."""
    monkeypatch.setenv("MOODLE_URL", BASE_URL)
    monkeypatch.setenv("MOODLE_TOKEN", "test-token")


def route_by_function(**payloads: Any) -> respx.Route:
    """Dispatch the single REST endpoint on the wsfunction being requested."""

    def responder(request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        for function, payload in payloads.items():
            if f"wsfunction={function}" in body:
                return httpx.Response(200, json=payload)
        return httpx.Response(200, json={"errorcode": "unmocked", "message": body})

    return respx.post(REST_URL).mock(side_effect=responder)


# -- search_courses ----------------------------------------------------------------


@respx.mock
def test_search_courses_matches_module_and_link_names(
    courses_payload: dict[str, Any], contents_payload: list[dict[str, Any]]
) -> None:
    route_by_function(
        core_course_get_enrolled_courses_by_timeline_classification=courses_payload,
        core_course_get_contents=contents_payload,
    )

    results = search_courses("slack")

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

    results = search_courses("entregas")

    assert results
    assert all(r["match"] == "section" for r in results)
    assert {r["course"] for r in results} == {"IOS460 - 123246", "I312 - 106931", "I310 - 106934"}


@respx.mock
def test_search_courses_is_case_insensitive_and_strips_the_query(
    courses_payload: dict[str, Any], contents_payload: list[dict[str, Any]]
) -> None:
    route_by_function(
        core_course_get_enrolled_courses_by_timeline_classification=courses_payload,
        core_course_get_contents=contents_payload,
    )

    assert search_courses("  SLACK  ") == search_courses("slack")


def test_search_courses_returns_empty_for_a_blank_query() -> None:
    """No network call either: an empty needle would otherwise match everything."""
    assert search_courses("   ") == []


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


# -- assignments and grades ----------------------------------------------------------


@respx.mock
def test_get_assignments_resolves_course_and_labels_it(
    courses_payload: dict[str, Any], assignments_payload: dict[str, Any]
) -> None:
    route_by_function(
        core_course_get_enrolled_courses_by_timeline_classification=courses_payload,
        mod_assign_get_assignments=assignments_payload,
    )

    results = get_assignments("IOS460")

    assert results == [
        {
            "id": 40393,
            "course": "IOS460 - 123246",
            "name": "Actividad semana 1",
            "due_at": "2026-03-11",
            "max_grade": 100,
        }
    ]


@respx.mock
def test_get_assignment_status_reports_submission_and_grade(
    submission_status_payload: dict[str, Any],
) -> None:
    route_by_function(mod_assign_get_submission_status=submission_status_payload)

    result = get_assignment_status(40393)

    assert result["submitted"] is True
    assert result["graded"] is True
    assert result["grade"] == "90.00\xa0/\xa0100.00"
    assert result["submitted_files"] == ["Entrega - Semana 1.pdf"]


@respx.mock
def test_get_quizzes_resolves_course_and_labels_it(
    courses_payload: dict[str, Any], quizzes_payload: dict[str, Any]
) -> None:
    route_by_function(
        core_course_get_enrolled_courses_by_timeline_classification=courses_payload,
        mod_quiz_get_quizzes_by_courses=quizzes_payload,
    )

    results = get_quizzes("IOS460")

    assert results == [
        {
            "id": 42628,
            "course": "IOS460 - 123246",
            "name": "Actividad semana 2",
            "opens_at": "2026-03-13",
            "closes_at": "2026-03-19",
            "max_attempts": 1,
            "max_grade": 100,
        }
    ]


@respx.mock
def test_get_quiz_status_reports_attempts_and_grade(
    quiz_attempts_payload: dict[str, Any], quiz_best_grade_payload: dict[str, Any]
) -> None:
    route_by_function(
        mod_quiz_get_user_attempts=quiz_attempts_payload,
        mod_quiz_get_user_best_grade=quiz_best_grade_payload,
    )

    result = get_quiz_status(42628)

    assert result == {
        "attempts_used": 1,
        "last_attempt_state": "finished",
        "graded": True,
        "grade": 6.925,
        "grade_to_pass": 4,
    }


@respx.mock
def test_get_grade_summary_labels_courses_by_shortname(
    courses_payload: dict[str, Any],
    grades_overview_payload: dict[str, Any],
    site_info_payload: dict[str, Any],
) -> None:
    route_by_function(
        core_course_get_enrolled_courses_by_timeline_classification=courses_payload,
        core_webservice_get_site_info=site_info_payload,
        gradereport_overview_get_course_grades=grades_overview_payload,
    )

    results = get_grade_summary()

    assert results == [
        {"course": "IOS460 - 123246", "grade": "85.00"},
        {"course": "I312 - 106931", "grade": ""},
    ]


@respx.mock
def test_get_grades_returns_per_item_breakdown(
    courses_payload: dict[str, Any],
    grade_items_payload: dict[str, Any],
    site_info_payload: dict[str, Any],
) -> None:
    route_by_function(
        core_course_get_enrolled_courses_by_timeline_classification=courses_payload,
        core_webservice_get_site_info=site_info_payload,
        gradereport_user_get_grade_items=grade_items_payload,
    )

    results = get_grades("IOS460")

    assert [r["item"] for r in results] == ["TP1", "Curso total"]
    assert results[0]["grade"] == "10.00"


@respx.mock
def test_get_grades_surfaces_the_permission_error_instead_of_hiding_it(
    courses_payload: dict[str, Any],
    site_info_payload: dict[str, Any],
) -> None:
    """A course with no visible gradebook should fail loudly, not return an empty list."""
    route_by_function(
        core_course_get_enrolled_courses_by_timeline_classification=courses_payload,
        core_webservice_get_site_info=site_info_payload,
        gradereport_user_get_grade_items={
            "exception": "moodle_exception",
            "errorcode": "nopermissiontoviewgrades",
            "message": "No se pueden ver las calificaciones.",
        },
    )

    with pytest.raises(MoodleAPIError, match="nopermissiontoviewgrades"):
        get_grades("IOS460")
