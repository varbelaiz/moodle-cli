"""Tests for identifying and relaying a course's Panopto LTI launch.

The WS client is faked rather than routed through respx, the same split
``moodle_cli_anydoc`` uses: resolving course contents exercises webservice calls that
add nothing here. The launch/relay HTTP is genuinely this module's own responsibility,
so that goes through respx.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import cast

import httpx
import pytest
import respx
from moodle_cli_panopto import lti
from moodle_cli_panopto.errors import PanoptoError
from moodle_cli_panopto.moodle_login import MoodleWebSession

from conftest import BASE_URL, PANOPTO_HOST, PANOPTO_URL, lti_launch_html
from moodle_cli.client import MoodleClient
from moodle_cli.models import Module, Section

LAUNCH_URL = f"{BASE_URL}/mod/lti/launch.php"
PANOPTO_ACTION = f"{PANOPTO_URL}/Panopto/lti/lti.aspx"


class FakeWsClient:
    def __init__(self, sections: list[Section]) -> None:
        self._sections = sections
        self.get_course_contents_calls = 0

    def get_course_contents(self, course_id: int) -> list[Section]:
        self.get_course_contents_calls += 1
        return self._sections


def _lti_module(cmid: int, name: str) -> Module:
    return Module(id=cmid, name=name, modname="lti")


def _sections(*modules: Module) -> list[Section]:
    return [Section(id=1, name="General", section=0, modules=list(modules))]


def _session() -> MoodleWebSession:
    return MoodleWebSession(client=httpx.Client(base_url=BASE_URL), sesskey="sess-1")


@pytest.fixture(autouse=True)
def _reset_cache() -> Iterator[None]:
    lti.reset_cache()
    yield
    lti.reset_cache()


def test_establish_panopto_session_skips_a_non_panopto_tool_without_posting_to_it() -> None:
    sections = _sections(_lti_module(10, "Clases por Zoom"), _lti_module(20, "Clases Grabadas"))
    ws = cast(MoodleClient, FakeWsClient(sections))
    moodle = _session()

    with respx.mock:
        zoom_route = respx.get(LAUNCH_URL, params={"id": "10"}).mock(
            return_value=httpx.Response(
                200, text=lti_launch_html("https://zoom.us/lti", {"a": "1"})
            )
        )
        respx.get(LAUNCH_URL, params={"id": "20"}).mock(
            return_value=httpx.Response(
                200, text=lti_launch_html(PANOPTO_ACTION, {"oauth_signature": "sig-x"})
            )
        )
        panopto_post = respx.post(PANOPTO_ACTION).mock(return_value=httpx.Response(200))

        client, host = lti.establish_panopto_session(moodle, ws, BASE_URL, 1)

    assert host == PANOPTO_HOST
    assert zoom_route.called
    assert panopto_post.called
    assert b"oauth_signature=sig-x" in panopto_post.calls.last.request.content
    client.close()
    moodle.client.close()


def test_establish_panopto_session_caches_the_working_cmid() -> None:
    sections = _sections(_lti_module(10, "Clases por Zoom"), _lti_module(20, "Clases Grabadas"))
    ws = cast(MoodleClient, FakeWsClient(sections))

    with respx.mock:
        zoom_route = respx.get(LAUNCH_URL, params={"id": "10"}).mock(
            return_value=httpx.Response(200, text=lti_launch_html("https://zoom.us/lti", {}))
        )
        respx.get(LAUNCH_URL, params={"id": "20"}).mock(
            return_value=httpx.Response(200, text=lti_launch_html(PANOPTO_ACTION, {}))
        )
        respx.post(PANOPTO_ACTION).mock(return_value=httpx.Response(200))

        first = _session()
        client, _host = lti.establish_panopto_session(first, ws, BASE_URL, 1)
        client.close()
        first.client.close()

        second = _session()
        client, _host = lti.establish_panopto_session(second, ws, BASE_URL, 1)
        client.close()
        second.client.close()

    # The cached cmid (20) is tried first on the second call, so the non-Panopto
    # module (10) is never probed a second time.
    assert zoom_route.call_count == 1


def test_establish_panopto_session_skips_the_course_contents_call_on_a_cache_hit() -> None:
    sections = _sections(_lti_module(20, "Clases Grabadas"))
    fake = FakeWsClient(sections)
    ws = cast(MoodleClient, fake)

    with respx.mock:
        respx.get(LAUNCH_URL, params={"id": "20"}).mock(
            return_value=httpx.Response(200, text=lti_launch_html(PANOPTO_ACTION, {}))
        )
        respx.post(PANOPTO_ACTION).mock(return_value=httpx.Response(200))

        first = _session()
        client, _host = lti.establish_panopto_session(first, ws, BASE_URL, 1)
        client.close()
        first.client.close()
        assert fake.get_course_contents_calls == 1

        second = _session()
        client, _host = lti.establish_panopto_session(second, ws, BASE_URL, 1)
        client.close()
        second.client.close()

    # A cache hit must not re-list the course's contents at all.
    assert fake.get_course_contents_calls == 1


def test_establish_panopto_session_raises_when_the_panopto_relay_post_fails() -> None:
    """A non-2xx from Panopto's own launch endpoint must not be treated as success."""
    sections = _sections(_lti_module(20, "Clases Grabadas"))
    ws = cast(MoodleClient, FakeWsClient(sections))
    moodle = _session()

    with respx.mock:
        respx.get(LAUNCH_URL, params={"id": "20"}).mock(
            return_value=httpx.Response(200, text=lti_launch_html(PANOPTO_ACTION, {}))
        )
        respx.post(PANOPTO_ACTION).mock(return_value=httpx.Response(500))

        with pytest.raises(PanoptoError):
            lti.establish_panopto_session(moodle, ws, BASE_URL, 1)

    moodle.client.close()


def test_parse_launch_form_ignores_hidden_inputs_after_the_form_closes() -> None:
    """A stray hidden input elsewhere on the page must not overwrite a real launch field."""
    markup = (
        '<form action="https://panopto.example/lti.aspx" method="post">'
        '<input type="hidden" name="oauth_signature" value="real-signature"/>'
        "</form>"
        '<input type="hidden" name="oauth_signature" value="clobbered"/>'
    )

    parsed = lti._parse_launch_form(markup)

    assert parsed is not None
    _action, fields = parsed
    assert fields["oauth_signature"] == "real-signature"


def test_establish_panopto_session_raises_when_no_tool_is_panopto() -> None:
    sections = _sections(_lti_module(10, "Clases por Zoom"))
    ws = cast(MoodleClient, FakeWsClient(sections))
    moodle = _session()

    with respx.mock:
        respx.get(LAUNCH_URL, params={"id": "10"}).mock(
            return_value=httpx.Response(200, text=lti_launch_html("https://zoom.us/lti", {}))
        )
        with pytest.raises(PanoptoError, match="no Panopto activity"):
            lti.establish_panopto_session(moodle, ws, BASE_URL, 1)

    moodle.client.close()
