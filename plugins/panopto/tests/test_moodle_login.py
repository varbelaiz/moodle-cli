"""Tests for the cookie-authenticated Moodle login.

respx-mocked: this is exactly the raw HTTP this plugin is genuinely responsible for --
scraping a login token, posting credentials, scraping the resulting sesskey -- so
nothing here is faked away.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from moodle_cli_panopto.errors import PanoptoError
from moodle_cli_panopto.moodle_login import login

from conftest import BASE_URL, dashboard_html, login_error_html, login_page_html


def test_login_happy_path_redirect_carries_the_sesskey() -> None:
    with respx.mock:
        respx.get(f"{BASE_URL}/login/index.php").mock(
            return_value=httpx.Response(200, text=login_page_html("tok-1"))
        )
        respx.post(f"{BASE_URL}/login/index.php").mock(
            return_value=httpx.Response(303, headers={"Location": "/my/"})
        )
        respx.get(f"{BASE_URL}/my/").mock(
            return_value=httpx.Response(200, text=dashboard_html("sess1"))
        )

        session = login(BASE_URL, "ana", "hunter2")

    assert session.sesskey == "sess1"
    session.client.close()


def test_login_falls_back_to_the_dashboard_when_the_landing_page_lacks_a_sesskey() -> None:
    with respx.mock:
        respx.get(f"{BASE_URL}/login/index.php").mock(
            return_value=httpx.Response(200, text=login_page_html())
        )
        respx.post(f"{BASE_URL}/login/index.php").mock(
            return_value=httpx.Response(303, headers={"Location": "/course/view.php?id=1"})
        )
        respx.get(f"{BASE_URL}/course/view.php").mock(
            return_value=httpx.Response(200, text="<p>no sesskey on this page</p>")
        )
        respx.get(f"{BASE_URL}/my/").mock(
            return_value=httpx.Response(200, text=dashboard_html("sess2"))
        )

        session = login(BASE_URL, "ana", "hunter2")

    assert session.sesskey == "sess2"
    session.client.close()


def test_login_raises_when_the_credentials_are_rejected() -> None:
    with respx.mock:
        respx.get(f"{BASE_URL}/login/index.php").mock(
            return_value=httpx.Response(200, text=login_page_html("tok-1"))
        )
        respx.post(f"{BASE_URL}/login/index.php").mock(
            return_value=httpx.Response(200, text=login_error_html())
        )

        with pytest.raises(PanoptoError, match="rejected"):
            login(BASE_URL, "ana", "wrong-password")


def test_login_raises_when_no_logintoken_is_found() -> None:
    with respx.mock:
        respx.get(f"{BASE_URL}/login/index.php").mock(
            return_value=httpx.Response(200, text="<p>no form here</p>")
        )

        with pytest.raises(PanoptoError, match="login token"):
            login(BASE_URL, "ana", "hunter2")


def test_login_raises_when_no_sesskey_is_found_anywhere() -> None:
    with respx.mock:
        respx.get(f"{BASE_URL}/login/index.php").mock(
            return_value=httpx.Response(200, text=login_page_html("tok-1"))
        )
        respx.post(f"{BASE_URL}/login/index.php").mock(
            return_value=httpx.Response(303, headers={"Location": "/my/"})
        )
        respx.get(f"{BASE_URL}/my/").mock(
            return_value=httpx.Response(200, text="<p>no sesskey anywhere</p>")
        )

        with pytest.raises(PanoptoError, match="sesskey"):
            login(BASE_URL, "ana", "hunter2")
