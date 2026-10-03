"""Signing in to Panopto through the campus.

Success has to be read from Panopto's auth cookie: every way this sign-in fails ends on
a page that answers 200.
"""

from __future__ import annotations

from dataclasses import replace

import httpx
import pytest
import respx
from moodle_cli_panopto.errors import PanoptoError
from moodle_cli_panopto.moodle_login import MoodleWebSession
from moodle_cli_panopto.recordings import Recording
from moodle_cli_panopto.sso import open_panopto_session

from conftest import BASE_URL, PANOPTO_HOST, PANOPTO_INSTANCE, mock_panopto_sign_in

RECORDING = Recording(id="aaa", name="Clase 1", host=PANOPTO_HOST, instance=PANOPTO_INSTANCE)


def _moodle(*, logged_in: bool = True) -> MoodleWebSession:
    cookies = httpx.Cookies()
    if logged_in:
        cookies.set("MoodleSession", "moodle-1", domain="campus.example.edu", path="/")
    return MoodleWebSession(client=httpx.Client(base_url=BASE_URL, cookies=cookies), sesskey="s")


@respx.mock
def test_sign_in_bounces_through_the_campus_with_the_moodle_session() -> None:
    mock_panopto_sign_in()

    panopto = open_panopto_session(_moodle(), RECORDING)
    panopto.close()

    assert panopto.cookies.get(".ASPXAUTH") == "signed-in"


@respx.mock
def test_sign_in_without_a_moodle_session_raises() -> None:
    """The campus answers a request it cannot vouch for with its own login page."""
    mock_panopto_sign_in()

    with pytest.raises(PanoptoError, match="did not accept the campus sign-in"):
        open_panopto_session(_moodle(logged_in=False), RECORDING)


@respx.mock
def test_sign_in_rejected_by_panopto_raises() -> None:
    mock_panopto_sign_in(accepted=False)

    with pytest.raises(PanoptoError, match="did not accept the campus sign-in"):
        open_panopto_session(_moodle(), RECORDING)


def test_sign_in_needs_the_instance_the_recording_link_names() -> None:
    with pytest.raises(PanoptoError, match="names no Panopto instance"):
        open_panopto_session(_moodle(), replace(RECORDING, instance=None))
