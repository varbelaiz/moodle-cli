"""Cookie-authenticated login against the Moodle campus itself.

Nothing this plugin needs -- the recordings block, the campus endpoint that signs the
user in to Panopto -- is reachable through the REST web-service surface
``moodle_cli.session`` builds a client for. Those are internal-AJAX and page-rendering
endpoints, gated on a ``MoodleSession`` cookie and a ``sesskey``, the same as a browser
tab.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from html.parser import HTMLParser
from http.cookiejar import Cookie

import httpx

from moodle_cli_panopto.errors import PanoptoError, wrap_http_errors

_LOGIN_PATH = "/login/index.php"
_DASHBOARD_PATH = "/my/"
_MFA_PATH = "/admin/tool/mfa/auth.php"
_MFA_ATTEMPTS = 3
#: The campus names its "trust this device" cookie after the user id it was issued to.
_TRUST_COOKIE_PREFIX = "MFA_TOKEN_"

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


class _MfaFormParser(HTMLParser):
    """Extracts the action and the submittable fields of the form asking for a code.

    The MFA page carries a second form (cancelling MFA logs out), so the right one is
    the form holding a ``verificationcode`` input, not merely the first.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.action: str | None = None
        self.fields: dict[str, str] = {}
        self._form: tuple[str | None, dict[str, str]] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "form":
            self._form = (attributes.get("action"), {})
        elif tag == "input" and self._form is not None:
            name = attributes.get("name")
            if name is not None and attributes.get("type") not in ("submit", "checkbox"):
                self._form[1][name] = attributes.get("value") or ""

    def handle_endtag(self, tag: str) -> None:
        if tag != "form" or self._form is None:
            return
        action, fields = self._form
        if self.action is None and action is not None and "verificationcode" in fields:
            self.action, self.fields = action, fields
        self._form = None


def _parse_mfa_form(html: str) -> tuple[str, dict[str, str]] | None:
    parser = _MfaFormParser()
    parser.feed(html)
    return (parser.action, parser.fields) if parser.action is not None else None


def _on_mfa_page(response: httpx.Response) -> bool:
    return response.url.path.endswith(_MFA_PATH)


def _pass_mfa(
    client: httpx.Client,
    base_url: str,
    page: httpx.Response,
    ask_code: Callable[[], str] | None,
) -> httpx.Response:
    """Submit codes from ASK_CODE on the MFA PAGE until the campus lets the session through.

    Every submission asks the campus to trust this device, so the cookie it issues
    spares later logins the step. Returns the first page past MFA.
    """
    if ask_code is None:
        raise PanoptoError(
            f"{base_url}: the campus requires a multi-factor verification code after login, "
            "and there is no terminal to enter it in; run any `moodle panopto` command in a "
            "terminal once to trust this device"
        )
    for _ in range(_MFA_ATTEMPTS):
        form = _parse_mfa_form(page.text)
        if form is None:
            raise PanoptoError(f"{base_url}: could not find the verification code form")
        action, fields = form
        fields.update(verificationcode=ask_code().strip(), factor_token_trust="1")
        with wrap_http_errors(f"{base_url}: the verification code request failed"):
            page = client.post(action, data=fields)
            page.raise_for_status()
        if not _on_mfa_page(page):
            return page
    raise PanoptoError(f"{base_url}: the verification code was rejected {_MFA_ATTEMPTS} times")


def _issued_trust_cookie(cookies: httpx.Cookies) -> Cookie | None:
    """The trust cookie the campus set in this client, told apart from a stored one by
    its expiry: only the campus's own ``Set-Cookie`` carries one."""
    for cookie in cookies.jar:
        if cookie.name.startswith(_TRUST_COOKIE_PREFIX) and cookie.expires is not None:
            return cookie
    return None


@dataclass
class MoodleWebSession:
    """A cookie-authenticated session against Moodle, distinct from the WS-token client."""

    client: httpx.Client
    sesskey: str
    trusted_device: Cookie | None = None
    """The trust cookie the campus issued during this login's MFA step, for the caller
    to persist; None when the login needed no MFA step."""


def login(
    base_url: str,
    username: str,
    password: str,
    *,
    trusted_device: Cookie | None = None,
    ask_code: Callable[[], str] | None = None,
) -> MoodleWebSession:
    """Authenticate against ``base_url`` with a Moodle username/password, cookie-style.

    A ``trusted_device`` cookie from an earlier login lets the campus skip its MFA step.
    Without one, the campus emails a verification code and ``ask_code`` must return it;
    with no ``ask_code`` to call, the MFA step is an error.

    Raises PanoptoError if the login page's anti-CSRF token or the resulting session's
    sesskey cannot be found -- the campus changed its markup, or SSO stands in the way
    of a plain username+password form -- or if the campus rejects the credentials or the
    verification code. The caller owns the returned session's ``client`` and must close it.
    """
    client = httpx.Client(base_url=base_url.rstrip("/"), timeout=30, follow_redirects=True)
    if trusted_device is not None:
        client.cookies.jar.set_cookie(trusted_device)
    try:
        with wrap_http_errors(f"{base_url}: could not reach the login page"):
            login_page = client.get(_LOGIN_PATH)
            login_page.raise_for_status()
        logintoken = _scrape(_LOGINTOKEN_RES, login_page.text)
        if logintoken is None:
            raise PanoptoError(f"{base_url}: could not find a login token on the login page")

        with wrap_http_errors(f"{base_url}: the login request failed"):
            response = client.post(
                _LOGIN_PATH,
                data={"username": username, "password": password, "logintoken": logintoken},
            )
            response.raise_for_status()

        # A rejected login re-renders the login form -- either at the same URL, or (an
        # interstitial the campus's auth flow inserted) at a different one that still
        # carries a fresh logintoken -- rather than redirecting on to the dashboard.
        still_showing_the_form = _scrape(_LOGINTOKEN_RES, response.text) is not None
        if response.url.path.rstrip("/") == _LOGIN_PATH.rstrip("/") or still_showing_the_form:
            raise PanoptoError(f"{base_url}: login was rejected for {username!r}")

        issued = None
        if _on_mfa_page(response):
            response = _pass_mfa(client, base_url, response, ask_code)
            issued = _issued_trust_cookie(client.cookies)

        sesskey = _scrape(_SESSKEY_RES, response.text)
        if sesskey is None:
            with wrap_http_errors(f"{base_url}: could not reach the dashboard"):
                dashboard = client.get(_DASHBOARD_PATH)
                dashboard.raise_for_status()
            sesskey = _scrape(_SESSKEY_RES, dashboard.text)
        if sesskey is None:
            raise PanoptoError(f"{base_url}: logged in but could not find a sesskey")

        return MoodleWebSession(client=client, sesskey=sesskey, trusted_device=issued)
    except BaseException:
        client.close()
        raise
