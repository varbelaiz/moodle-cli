"""Client tests: error detection, parameter encoding, filter mapping, pagination."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
import respx

from moodle_cli.client import SORTS, VIEWS, MoodleClient, _flatten_params, check_api_error
from moodle_cli.errors import MoodleAPIError, MoodleError
from tests.conftest import BASE_URL, REST_URL


@pytest.fixture
def client() -> MoodleClient:
    return MoodleClient(BASE_URL, "test-token")


def posted_params(request: httpx.Request) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(request.content.decode()).items()}


# -- error detection -------------------------------------------------------------


def test_check_api_error_passes_lists_and_plain_dicts() -> None:
    check_api_error([{"id": 1}])
    check_api_error({"courses": []})


@pytest.mark.parametrize(
    "body",
    [
        {"exception": "moodle_exception", "errorcode": "invalidtoken", "message": "Invalid token"},
        {"errorcode": "accessexception", "message": "Access control exception"},
    ],
)
def test_check_api_error_raises_on_error_payloads(body: dict[str, Any]) -> None:
    with pytest.raises(MoodleAPIError):
        check_api_error(body, function="core_course_get_contents")


@respx.mock
def test_call_raises_on_http_200_error_body(client: MoodleClient) -> None:
    respx.post(REST_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "exception": "moodle_exception",
                "errorcode": "invalidtoken",
                "message": "Invalid token - token not found",
            },
        )
    )
    with pytest.raises(MoodleAPIError) as excinfo:
        client.get_site_info()
    assert excinfo.value.errorcode == "invalidtoken"


@respx.mock
def test_call_raises_on_non_json_response(client: MoodleClient) -> None:
    respx.post(REST_URL).mock(return_value=httpx.Response(200, text="<html>maintenance</html>"))
    with pytest.raises(MoodleError, match="non-JSON"):
        client.get_site_info()


# -- parameter encoding ----------------------------------------------------------


def test_flatten_params_encodes_php_style_arrays() -> None:
    flat = _flatten_params({"courseid": 5, "options": [{"name": "limitfrom", "value": 0}]})
    assert flat == {
        "courseid": "5",
        "options[0][name]": "limitfrom",
        "options[0][value]": "0",
    }


def test_flatten_params_drops_none_and_encodes_bools() -> None:
    assert _flatten_params({"a": None, "b": True, "c": False}) == {"b": "1", "c": "0"}


# -- filters ---------------------------------------------------------------------


@respx.mock
def test_list_courses_maps_public_names_to_moodle_values(
    client: MoodleClient, courses_payload: dict[str, Any]
) -> None:
    route = respx.post(REST_URL).mock(return_value=httpx.Response(200, json=courses_payload))

    client.list_courses(view="starred", sort="last-accessed")

    params = posted_params(route.calls[0].request)
    assert params["classification"] == "favourites"
    assert params["sort"] == "ul.timeaccess desc"
    assert params["wsfunction"] == "core_course_get_enrolled_courses_by_timeline_classification"


def test_view_and_sort_tables_cover_the_dashboard_options() -> None:
    assert set(VIEWS) == {
        "all",
        "all-including-hidden",
        "in-progress",
        "future",
        "past",
        "starred",
        "hidden",
    }
    assert set(SORTS) == {"name", "last-accessed"}


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [({"view": "bogus"}, "Unknown view"), ({"sort": "bogus"}, "Unknown sort")],
)
def test_list_courses_rejects_unknown_filters(
    client: MoodleClient, kwargs: dict[str, str], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        client.list_courses(**kwargs)


# -- contents and participants ---------------------------------------------------


@respx.mock
def test_get_course_contents_keeps_only_real_files(
    client: MoodleClient, contents_payload: list[dict[str, Any]]
) -> None:
    respx.post(REST_URL).mock(return_value=httpx.Response(200, json=contents_payload))

    sections = client.get_course_contents(101)
    files = [f for s in sections for m in s.modules for f in m.files]

    # 1 resource + 2 folder entries; the url module's link is excluded.
    assert len(files) == 3
    assert all(f.type == "file" for f in files)
    # External-repository files still count: they are served through pluginfile.php.
    assert any(f.isexternalfile for f in files)


@respx.mock
def test_get_course_contents_surfaces_url_module_targets_as_links(
    client: MoodleClient, contents_payload: list[dict[str, Any]]
) -> None:
    respx.post(REST_URL).mock(return_value=httpx.Response(200, json=contents_payload))

    sections = client.get_course_contents(101)
    links = [link for s in sections for m in s.modules for link in m.links]

    assert len(links) == 1
    assert links[0].filename == "Slack de la Materia"
    assert links[0].fileurl == "https://slack.example.com/join"
    # A url module's target never shows up in `files`: there is nothing to download.
    assert all(
        link not in [f for s in sections for m in s.modules for f in m.files] for link in links
    )


@respx.mock
def test_get_participants_pages_until_short_page(client: MoodleClient) -> None:
    from moodle_cli.client import _PARTICIPANT_PAGE_SIZE

    full = [{"id": i, "fullname": f"User {i}", "roles": []} for i in range(_PARTICIPANT_PAGE_SIZE)]
    tail = [{"id": 9999, "fullname": "Last One", "roles": []}]
    route = respx.post(REST_URL).mock(
        side_effect=[
            httpx.Response(200, json=full),
            httpx.Response(200, json=tail),
        ]
    )

    people = client.get_participants(101)

    assert len(people) == _PARTICIPANT_PAGE_SIZE + 1
    assert posted_params(route.calls[1].request)["options[0][value]"] == str(_PARTICIPANT_PAGE_SIZE)


# -- announcements -----------------------------------------------------------------


@respx.mock
def test_get_announcements_only_reads_news_forums(
    client: MoodleClient,
    forums_payload: list[dict[str, Any]],
    discussions_payload: dict[str, Any],
) -> None:
    route = respx.post(REST_URL).mock(
        side_effect=[
            httpx.Response(200, json=forums_payload),
            httpx.Response(200, json=discussions_payload),
        ]
    )

    announcements = client.get_announcements(course_id=101)

    # Two calls total: the general-discussion forum (502) is never queried.
    assert len(route.calls) == 2
    assert posted_params(route.calls[1].request)["forumid"] == "501"

    assert [a.id for a in announcements] == [9001, 9000]  # newest first
    assert all(a.courseid == 101 for a in announcements)
    assert "<strong>" not in announcements[0].message_text
    assert "S004" in announcements[0].message_text


@respx.mock
def test_get_announcements_returns_empty_without_a_news_forum(client: MoodleClient) -> None:
    respx.post(REST_URL).mock(return_value=httpx.Response(200, json=[]))
    assert client.get_announcements(course_id=101) == []


# -- assignments -------------------------------------------------------------------


@respx.mock
def test_get_assignments_flattens_courses(
    client: MoodleClient, assignments_payload: dict[str, Any]
) -> None:
    respx.post(REST_URL).mock(return_value=httpx.Response(200, json=assignments_payload))

    assignments = client.get_assignments()

    assert len(assignments) == 1
    assert assignments[0].name == "Actividad semana 1"
    assert assignments[0].course == 101


@respx.mock
def test_get_assignment_status_extracts_submission_and_grade(
    client: MoodleClient, submission_status_payload: dict[str, Any]
) -> None:
    respx.post(REST_URL).mock(return_value=httpx.Response(200, json=submission_status_payload))

    status = client.get_assignment_status(40393)

    assert status.submitted is True
    assert status.graded is True
    # &nbsp; arrives HTML-escaped and is decoded, not left literal.
    assert status.gradefordisplay == "90.00\xa0/\xa0100.00"
    assert status.submitted_files == ["Entrega - Semana 1.pdf"]


# -- quizzes ---------------------------------------------------------------------


@respx.mock
def test_get_quizzes_defaults_to_every_enrolled_course(
    client: MoodleClient, courses_payload: dict[str, Any], quizzes_payload: dict[str, Any]
) -> None:
    route = respx.post(REST_URL).mock(
        side_effect=[
            httpx.Response(200, json=courses_payload),
            httpx.Response(200, json=quizzes_payload),
        ]
    )

    quizzes = client.get_quizzes()

    assert len(quizzes) == 1
    assert quizzes[0].name == "Actividad semana 2"
    assert quizzes[0].course == 101
    params = posted_params(route.calls[1].request)
    assert {params[k] for k in params if k.startswith("courseids[")} == {"101", "102", "103"}


@respx.mock
def test_get_quiz_status_combines_attempts_and_best_grade(
    client: MoodleClient,
    quiz_attempts_payload: dict[str, Any],
    quiz_best_grade_payload: dict[str, Any],
) -> None:
    respx.post(REST_URL).mock(
        side_effect=[
            httpx.Response(200, json=quiz_attempts_payload),
            httpx.Response(200, json=quiz_best_grade_payload),
        ]
    )

    status = client.get_quiz_status(42628)

    assert status.attempt_count == 1
    assert status.last_state == "finished"
    assert status.has_grade is True
    assert status.grade == 6.925
    assert status.grade_to_pass == 4


@respx.mock
def test_get_quiz_status_handles_no_attempts_yet(client: MoodleClient) -> None:
    respx.post(REST_URL).mock(
        side_effect=[
            httpx.Response(200, json={"attempts": [], "warnings": []}),
            httpx.Response(200, json={"hasgrade": False, "gradetopass": 60, "warnings": []}),
        ]
    )

    status = client.get_quiz_status(42628)

    assert status.attempt_count == 0
    assert status.last_state is None
    assert status.has_grade is False


# -- grades ----------------------------------------------------------------------


@respx.mock
def test_get_grade_overview_uses_the_tokens_own_user_id(
    client: MoodleClient, grades_overview_payload: dict[str, Any]
) -> None:
    route = respx.post(REST_URL).mock(
        side_effect=[
            httpx.Response(200, json={"userid": 63643, "functions": []}),
            httpx.Response(200, json=grades_overview_payload),
        ]
    )

    grades = client.get_grade_overview()

    assert posted_params(route.calls[1].request)["userid"] == "63643"
    assert [g.courseid for g in grades] == [101, 102]
    assert grades[0].grade == "85.00"


@respx.mock
def test_get_grade_items_returns_the_first_users_items(
    client: MoodleClient, grade_items_payload: dict[str, Any]
) -> None:
    respx.post(REST_URL).mock(
        side_effect=[
            httpx.Response(200, json={"userid": 63643, "functions": []}),
            httpx.Response(200, json=grade_items_payload),
        ]
    )

    items = client.get_grade_items(101)

    assert [i.itemname for i in items] == ["TP1", "Curso total"]
    # The course-total row has no backing activity: itemmodule arrives null, not "".
    assert items[1].itemmodule is None
    assert items[0].gradeformatted == "10.00"


@respx.mock
def test_get_grade_items_surfaces_missing_gradebook_permission(client: MoodleClient) -> None:
    """A per-course setting, not a token-wide block: get_grade_overview is unaffected."""
    respx.post(REST_URL).mock(
        side_effect=[
            httpx.Response(200, json={"userid": 63643, "functions": []}),
            httpx.Response(
                200,
                json={
                    "exception": "moodle_exception",
                    "errorcode": "nopermissiontoviewgrades",
                    "message": "No se pueden ver las calificaciones.",
                },
            ),
        ]
    )

    with pytest.raises(MoodleAPIError) as excinfo:
        client.get_grade_items(101)
    assert excinfo.value.errorcode == "nopermissiontoviewgrades"


# -- course resolution -----------------------------------------------------------


@pytest.fixture
def resolving_client(courses_payload: dict[str, Any]) -> MoodleClient:
    respx.post(REST_URL).mock(return_value=httpx.Response(200, json=courses_payload))
    return MoodleClient(BASE_URL, "test-token")


@respx.mock
def test_resolve_course_by_id(resolving_client: MoodleClient) -> None:
    assert resolving_client.resolve_course("102").shortname == "I312 - 106931"


@respx.mock
def test_resolve_course_by_shortname_prefix(resolving_client: MoodleClient) -> None:
    """ "IOS460" must find "IOS460 - 123246"; nobody types the internal course number."""
    assert resolving_client.resolve_course("IOS460").id == 101


@respx.mock
def test_resolve_course_is_case_insensitive(resolving_client: MoodleClient) -> None:
    assert resolving_client.resolve_course("ios460").id == 101


@respx.mock
def test_resolve_course_reports_ambiguity(resolving_client: MoodleClient) -> None:
    with pytest.raises(MoodleError, match="ambiguous"):
        resolving_client.resolve_course("I3")


@respx.mock
def test_resolve_course_reports_unknown_reference(resolving_client: MoodleClient) -> None:
    with pytest.raises(MoodleError, match="No enrolled course"):
        resolving_client.resolve_course("NOPE999")


@respx.mock
def test_resolve_course_reports_unknown_id(resolving_client: MoodleClient) -> None:
    with pytest.raises(MoodleError, match="id 4242"):
        resolving_client.resolve_course("4242")
