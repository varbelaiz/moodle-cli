"""Tests for the cookie-authenticated Moodle login.

respx-mocked: this is exactly the raw HTTP this plugin is genuinely responsible for --
scraping a login token, posting credentials, scraping the resulting sesskey -- so
nothing here is faked away.
"""

from __future__ import annotations

from urllib.parse import parse_qs

import httpx
import pytest
import respx
from moodle_cli_panopto.errors import PanoptoError
from moodle_cli_panopto.moodle_login import login

from conftest import BASE_URL, dashboard_html, login_error_html, login_page_html, mfa_page_html

MFA_URL = f"{BASE_URL}/admin/tool/mfa/auth.php"
TRUST_COOKIE = "MFA_TOKEN_42=trust-secret; Expires=Wed, 01 Jan 2031 00:00:00 GMT; Path=/"


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


def test_login_wraps_an_http_error_as_panopto_error() -> None:
    """A 5xx on the login page itself must never escape as a raw httpx error."""
    with respx.mock:
        respx.get(f"{BASE_URL}/login/index.php").mock(return_value=httpx.Response(500))

        with pytest.raises(PanoptoError):
            login(BASE_URL, "ana", "hunter2")


def test_login_raises_when_an_interstitial_still_shows_a_login_form() -> None:
    """A rejected login can land somewhere other than /login/index.php and still be
    a login form -- e.g. a campus-specific auth controller -- and must be caught too."""
    with respx.mock:
        respx.get(f"{BASE_URL}/login/index.php").mock(
            return_value=httpx.Response(200, text=login_page_html("tok-1"))
        )
        respx.post(f"{BASE_URL}/login/index.php").mock(
            return_value=httpx.Response(303, headers={"Location": "/login/interstitial.php"})
        )
        respx.get(f"{BASE_URL}/login/interstitial.php").mock(
            return_value=httpx.Response(200, text=login_page_html("tok-2"))
        )

        with pytest.raises(PanoptoError, match="rejected"):
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


def _mock_login_landing_on_mfa() -> None:
    respx.get(f"{BASE_URL}/login/index.php").mock(
        return_value=httpx.Response(200, text=login_page_html("tok-1"))
    )
    respx.post(f"{BASE_URL}/login/index.php").mock(
        return_value=httpx.Response(303, headers={"Location": "/admin/tool/mfa/auth.php"})
    )
    respx.get(MFA_URL).mock(return_value=httpx.Response(200, text=mfa_page_html("sessmfa")))


def test_login_submits_the_entered_code_and_asks_the_campus_to_trust_the_device() -> None:
    with respx.mock:
        _mock_login_landing_on_mfa()
        submit = respx.post(MFA_URL).mock(
            return_value=httpx.Response(
                303, headers=[("Location", "/my/"), ("Set-Cookie", TRUST_COOKIE)]
            )
        )
        respx.get(f"{BASE_URL}/my/").mock(
            return_value=httpx.Response(200, text=dashboard_html("sessmfa"))
        )

        session = login(BASE_URL, "ana", "hunter2", ask_code=lambda: " 123456\n")

    form = {k: v[0] for k, v in parse_qs(submit.calls.last.request.content.decode()).items()}
    assert form["verificationcode"] == "123456"
    assert form["factor_token_trust"] == "1"
    assert form["sesskey"] == "sessmfa"
    assert "logout" not in form
    assert session.sesskey == "sessmfa"
    assert session.trusted_device is not None
    assert (session.trusted_device.name, session.trusted_device.value) == (
        "MFA_TOKEN_42",
        "trust-secret",
    )
    session.client.close()


def test_login_raises_on_mfa_when_there_is_no_way_to_ask_for_a_code() -> None:
    with respx.mock:
        _mock_login_landing_on_mfa()

        with pytest.raises(PanoptoError, match="multi-factor verification code"):
            login(BASE_URL, "ana", "hunter2")


def test_login_gives_up_after_three_rejected_codes() -> None:
    with respx.mock:
        _mock_login_landing_on_mfa()
        submit = respx.post(MFA_URL).mock(
            return_value=httpx.Response(200, text=mfa_page_html("sessmfa"))
        )

        with pytest.raises(PanoptoError, match="rejected 3 times"):
            login(BASE_URL, "ana", "hunter2", ask_code=lambda: "000000")

    assert submit.call_count == 3


def test_login_with_a_trusted_device_cookie_skips_mfa_and_issues_none() -> None:
    stored = httpx.Cookies()
    stored.set("MFA_TOKEN_42", "trust-secret", domain="campus.example.edu", path="/")

    def dashboard(request: httpx.Request) -> httpx.Response:
        assert "MFA_TOKEN_42=trust-secret" in request.headers.get("cookie", "")
        return httpx.Response(200, text=dashboard_html("sess1"))

    with respx.mock:
        respx.get(f"{BASE_URL}/login/index.php").mock(
            return_value=httpx.Response(200, text=login_page_html("tok-1"))
        )
        respx.post(f"{BASE_URL}/login/index.php").mock(
            return_value=httpx.Response(303, headers={"Location": "/my/"})
        )
        respx.get(f"{BASE_URL}/my/").mock(side_effect=dashboard)

        session = login(
            BASE_URL,
            "ana",
            "hunter2",
            trusted_device=next(iter(stored.jar)),
            ask_code=lambda: pytest.fail("no code should be asked for"),
        )

    assert session.sesskey == "sess1"
    assert session.trusted_device is None
    session.client.close()
