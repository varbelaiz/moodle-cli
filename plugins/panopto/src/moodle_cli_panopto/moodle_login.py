"""Cookie-authenticated login against the Moodle campus itself.

Nothing this plugin needs -- the recordings block, the LTI launch that hands off to
Panopto -- is reachable through the REST web-service surface ``moodle_cli.session``
builds a client for. Those are internal-AJAX and page-rendering endpoints, gated on a
``MoodleSession`` cookie and a ``sesskey``, the same as a browser tab.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

from moodle_cli_panopto.errors import PanoptoError

_LOGIN_PATH = "/login/index.php"
_DASHBOARD_PATH = "/my/"

_LOGINTOKEN_RES = (
    re.compile(r'name=["\']logintoken["\'][^>]*?value=["\']([^"\']*)["\']'),
    re.compile(r'value=["\']([^"\']*)["\'][^>]*?name=["\']logintoken["\']'),
)
#: Two independent places a logged-in page names the current sesskey: the "Log out"
#: link every page footer carries, and the M.cfg JS config blob. Either is enough.
_SESSKEY_RES = (
    re.compile(r"logout\.php\?sesskey=([A-Za-z0-9]+)"),
    re.compile(r'"sesskey"\s*:\s*"([A-Za-z0-9]+)"'),
)


def _scrape(patterns: tuple[re.Pattern[str], ...], html: str) -> str | None:
    for pattern in patterns:
        match = pattern.search(html)
        if match:
            return match.group(1)
    return None


@dataclass
class MoodleWebSession:
    """A cookie-authenticated session against Moodle, distinct from the WS-token client."""

    client: httpx.Client
    sesskey: str


def login(base_url: str, username: str, password: str) -> MoodleWebSession:
    """Authenticate against ``base_url`` with a Moodle username/password, cookie-style.

    Raises PanoptoError if the login page's anti-CSRF token or the resulting session's
    sesskey cannot be found -- the campus changed its markup, or 2FA/SSO stands in the
    way of a plain username+password form -- or if the campus rejects the credentials.
    The caller owns the returned session's ``client`` and must close it.
    """
    client = httpx.Client(base_url=base_url.rstrip("/"), timeout=30, follow_redirects=True)
    try:
        login_page = client.get(_LOGIN_PATH)
        logintoken = _scrape(_LOGINTOKEN_RES, login_page.text)
        if logintoken is None:
            raise PanoptoError(f"{base_url}: could not find a login token on the login page")

        response = client.post(
            _LOGIN_PATH,
            data={"username": username, "password": password, "logintoken": logintoken},
        )
        # A rejected login re-renders the same form at the same URL rather than
        # redirecting on to the dashboard.
        if response.url.path.rstrip("/") == _LOGIN_PATH.rstrip("/"):
            raise PanoptoError(f"{base_url}: login was rejected for {username!r}")

        sesskey = _scrape(_SESSKEY_RES, response.text)
        if sesskey is None:
            dashboard = client.get(_DASHBOARD_PATH)
            sesskey = _scrape(_SESSKEY_RES, dashboard.text)
        if sesskey is None:
            raise PanoptoError(f"{base_url}: logged in but could not find a sesskey")

        return MoodleWebSession(client=client, sesskey=sesskey)
    except BaseException:
        client.close()
        raise
