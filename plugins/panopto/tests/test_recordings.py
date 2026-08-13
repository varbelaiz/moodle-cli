"""Tests for listing a course's Panopto recordings and resolving one (or several)."""

from __future__ import annotations

import httpx
import pytest
import respx
from moodle_cli_panopto.errors import PanoptoError
from moodle_cli_panopto.moodle_login import MoodleWebSession
from moodle_cli_panopto.recordings import (
    Recording,
    list_recordings,
    resolve_session,
    select_sessions,
)

from conftest import BASE_URL, PANOPTO_HOST, recording_link, recordings_fragment

AJAX_URL = f"{BASE_URL}/lib/ajax/service.php"


def _session() -> MoodleWebSession:
    return MoodleWebSession(client=httpx.Client(base_url=BASE_URL), sesskey="sess-1")


# -- list_recordings -------------------------------------------------------------------


def test_list_recordings_parses_the_block_fragment() -> None:
    fragment = recordings_fragment(
        recording_link("11111111-1111-1111-1111-111111111111", "Clase 1"),
        recording_link("22222222-2222-2222-2222-222222222222", "Clase 2 &amp; repaso"),
    )
    session = _session()
    with respx.mock:
        respx.post(AJAX_URL).mock(
            return_value=httpx.Response(200, json=[{"error": False, "data": fragment}])
        )
        recordings = list_recordings(session, 29272)
    session.client.close()

    assert recordings == [
        Recording(id="11111111-1111-1111-1111-111111111111", name="Clase 1", host=PANOPTO_HOST),
        Recording(
            id="22222222-2222-2222-2222-222222222222",
            name="Clase 2 & repaso",
            host=PANOPTO_HOST,
        ),
    ]


def test_list_recordings_raises_when_the_block_reports_an_error() -> None:
    session = _session()
    with respx.mock:
        respx.post(AJAX_URL).mock(
            return_value=httpx.Response(
                200, json=[{"error": True, "exception": {"message": "nopermission"}}]
            )
        )
        with pytest.raises(PanoptoError, match="nopermission"):
            list_recordings(session, 29272)
    session.client.close()


def test_list_recordings_returns_empty_for_a_course_with_none() -> None:
    session = _session()
    with respx.mock:
        respx.post(AJAX_URL).mock(
            return_value=httpx.Response(200, json=[{"error": False, "data": recordings_fragment()}])
        )
        assert list_recordings(session, 29272) == []
    session.client.close()


# -- resolve_session ---------------------------------------------------------------------

_RECORDINGS = [
    Recording(id="aaa", name="Clase 1 - Introduccion", host=PANOPTO_HOST),
    Recording(id="bbb", name="Clase 2 - Backend", host=PANOPTO_HOST),
    Recording(id="ccc", name="Clase 2 - Backend (repaso)", host=PANOPTO_HOST),
]


def test_resolve_session_matches_an_exact_delivery_id() -> None:
    assert resolve_session(_RECORDINGS, "bbb").id == "bbb"


def test_resolve_session_matches_an_exact_name() -> None:
    assert resolve_session(_RECORDINGS, "Clase 1 - Introduccion").id == "aaa"


def test_resolve_session_matches_a_unique_substring() -> None:
    assert resolve_session(_RECORDINGS, "introduccion").id == "aaa"


def test_resolve_session_raises_on_no_match() -> None:
    with pytest.raises(ValueError, match="no recording matches"):
        resolve_session(_RECORDINGS, "nothing like this")


def test_resolve_session_raises_on_an_ambiguous_substring() -> None:
    with pytest.raises(ValueError, match="ambiguous"):
        resolve_session(_RECORDINGS, "backend")


# -- select_sessions ---------------------------------------------------------------------


def test_select_sessions_with_no_filters_selects_everything() -> None:
    assert select_sessions(_RECORDINGS, None, None) == _RECORDINGS


def test_select_sessions_matches_an_exact_name() -> None:
    assert select_sessions(_RECORDINGS, {"Clase 1 - Introduccion"}, None) == [_RECORDINGS[0]]


def test_select_sessions_matches_an_exact_delivery_id() -> None:
    assert select_sessions(_RECORDINGS, {"ccc"}, None) == [_RECORDINGS[2]]


def test_select_sessions_matches_a_glob_pattern() -> None:
    assert select_sessions(_RECORDINGS, None, {"*Backend*"}) == _RECORDINGS[1:]


def test_select_sessions_unions_names_and_patterns() -> None:
    result = select_sessions(_RECORDINGS, {"aaa"}, {"*repaso*"})
    assert result == [_RECORDINGS[0], _RECORDINGS[2]]
