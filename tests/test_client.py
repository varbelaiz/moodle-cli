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
