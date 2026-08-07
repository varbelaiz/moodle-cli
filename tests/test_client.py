"""Client tests: error detection, parameter encoding, filter mapping, pagination."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx
from pydantic import ValidationError

from moodle_cli.client import SORTS, VIEWS, MoodleClient, _flatten_params, check_api_error
from moodle_cli.errors import MoodleAPIError, MoodleError
from tests.conftest import BASE_URL, REST_URL, posted_params


@pytest.fixture
def client() -> MoodleClient:
    return MoodleClient(BASE_URL, "test-token")


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

    announcements = client.get_announcements([101])

    # Two calls total: the general-discussion forum (502) is never queried.
    assert len(route.calls) == 2
    assert posted_params(route.calls[1].request)["forumid"] == "501"

    assert [a.id for a in announcements] == [9001, 9000]  # newest first
    assert all(a.courseid == 101 for a in announcements)
    assert "<strong>" not in announcements[0].message_text
    assert "S004" in announcements[0].message_text


@respx.mock
def test_get_announcements_returns_empty_without_a_news_forum(
    client: MoodleClient, forums_payload: list[dict[str, Any]]
) -> None:
    general_only = [f for f in forums_payload if f["type"] != "news"]
    route = respx.post(REST_URL).mock(return_value=httpx.Response(200, json=general_only))

    assert client.get_announcements([101]) == []
    assert len(route.calls) == 1  # no discussion read for a forum that carries no news


@respx.mock
def test_get_announcements_sweeps_dashboard_hidden_courses_too(
    client: MoodleClient, courses_payload: dict[str, Any]
) -> None:
    route = respx.post(REST_URL).mock(
        side_effect=[
            httpx.Response(200, json=courses_payload),
            httpx.Response(200, json=[]),
        ]
    )

    client.get_announcements()

    assert posted_params(route.calls[0].request)["classification"] == "allincludinghidden"
    assert posted_params(route.calls[1].request)["courseids[0]"] == "101"


@respx.mock
def test_get_announcements_rejects_a_forum_record_missing_its_course(client: MoodleClient) -> None:
    """A wire payload becomes a model before use, so a missing field fails by name."""
    respx.post(REST_URL).mock(return_value=httpx.Response(200, json=[{"id": 501, "type": "news"}]))

    with pytest.raises(ValidationError) as exc:
        client.get_announcements([101])

    assert "course" in str(exc.value)


@respx.mock
def test_get_announcements_raises_on_a_warning_beside_the_discussions(
    client: MoodleClient, forums_payload: list[dict[str, Any]]
) -> None:
    """A partial read must not be reported as an empty one."""
    respx.post(REST_URL).mock(
        side_effect=[
            httpx.Response(200, json=forums_payload),
            httpx.Response(
                200,
                json={
                    "discussions": [],
                    "warnings": [
                        {"warningcode": "errorreadingforum", "message": "Could not read the forum"}
                    ],
                },
            ),
        ]
    )

    with pytest.raises(MoodleAPIError) as exc:
        client.get_announcements([101])

    assert "errorreadingforum" in str(exc.value)


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
    # A course with nothing graded yet reports a null grade, not an empty string.
    assert grades[1].grade == ""


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

    assert [i.itemname for i in items] == ["TP1", None, None]
    assert items[0].gradeformatted == "10.00"


@respx.mock
def test_an_aggregate_grade_row_is_named_by_its_item_type(
    client: MoodleClient, grade_items_payload: dict[str, Any]
) -> None:
    """A course-total or category row carries no itemname and no itemmodule: both null."""
    respx.post(REST_URL).mock(
        side_effect=[
            httpx.Response(200, json={"userid": 63643, "functions": []}),
            httpx.Response(200, json=grade_items_payload),
        ]
    )

    items = client.get_grade_items(101)

    assert [i.label for i in items] == ["TP1", "Category subtotal", "Course total"]
    assert all(i.itemmodule is None for i in items[1:])
    # A null feedback reaches a str field and must not raise.
    assert items[-1].feedback == ""


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
