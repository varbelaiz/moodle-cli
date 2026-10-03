"""Shared test fixtures for the panopto plugin.

Self-contained rather than sharing the core suite's conftest: workspace members run
their tests independently. Registers its own ``--live`` option/skip machinery because
this plugin -- unlike anydoc -- has a live suite of its own.
"""

from __future__ import annotations

import httpx
import pytest
import respx

BASE_URL = "https://campus.example.edu"
PANOPTO_HOST = "campus.hosted.panopto.com"
PANOPTO_URL = f"https://{PANOPTO_HOST}"
PANOPTO_INSTANCE = "campusMoodle"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--live",
        action="store_true",
        default=False,
        help="run tests that hit the real campus using credentials from the environment",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--live"):
        return
    skip = pytest.mark.skip(reason="needs --live")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def isolated_env(
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """Keep the developer's real .env, saved settings and keyring out of the unit tests.

    Every non-live test here fakes its own client/session rather than resolving real
    credentials, but this stays as a safety net against a future test that forgets to.
    The keyring is an in-memory one per test: a login reads and writes the device-trust
    cookie through it.
    """
    if "live" in request.keywords:
        return
    config_dir = tmp_path_factory.mktemp("config")
    monkeypatch.setattr("moodle_cli.config._config_dir", lambda: config_dir)
    monkeypatch.setattr("moodle_cli.config._find_dotenv", lambda: None)
    monkeypatch.setattr("moodle_cli.config._ENV_LOADED", False)
    for var in ("MOODLE_URL", "MOODLE_USER", "MOODLE_PASS", "MOODLE_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    passwords: dict[tuple[str, str], str] = {}
    monkeypatch.setattr("keyring.get_password", lambda service, key: passwords.get((service, key)))
    monkeypatch.setattr(
        "keyring.set_password",
        lambda service, key, value: passwords.__setitem__((service, key), value),
    )


def recording_link(delivery_id: str, name: str, *, host: str = PANOPTO_HOST) -> str:
    """One `block_panopto_get_content`-style anchor, the shape recordings.py parses."""
    return f"<a href='https://{host}/Panopto/Pages/Viewer.aspx?id={delivery_id}&instance={PANOPTO_INSTANCE}'>{name}</a>"


def recordings_fragment(*links: str) -> str:
    return (
        "<div><b>Live sessions</b></div><div class='listItem'>No live sessions</div>"
        "<div class='sectionHeader'><b>Completed recordings</b></div>" + "".join(links)
    )


def login_page_html(logintoken: str = "tok-123") -> str:
    return f'<form><input type="hidden" name="logintoken" value="{logintoken}"></form>'


def dashboard_html(sesskey: str = "sess-abc") -> str:
    return f'<a href="/login/logout.php?sesskey={sesskey}">Log out</a>'


def login_error_html(logintoken: str = "tok-456") -> str:
    return (
        '<div class="loginerrors">Invalid login</div>'
        f'<form><input type="hidden" name="logintoken" value="{logintoken}"></form>'
    )


def mfa_page_html(sesskey: str = "sessmfa") -> str:
    """Moodle's MFA step: the code form, then the cancel form that logs out."""
    action = f"{BASE_URL}/admin/tool/mfa/auth.php"
    return (
        f'<script>M.cfg = {{"sesskey":"{sesskey}"}};</script>'
        f'<form action="{action}" method="post">'
        '<input name="factor" type="alphaext" value="email">'
        f'<input name="sesskey" type="hidden" value="{sesskey}">'
        '<input name="_qf__tool_mfa_local_form_login_form" type="hidden" value="1">'
        '<input name="verificationcode" type="text" value="">'
        '<input name="factor_token_trust" type="hidden" value="0">'
        '<input name="factor_token_trust" type="checkbox" value="1">'
        '<input name="submitbutton" type="submit" value="Continue">'
        "</form>"
        f'<form action="{action}" method="POST">'
        '<input name="logout" type="hidden" value="true">'
        f'<input name="sesskey" type="hidden" value="{sesskey}">'
        '<input name="cancelmfa" type="submit" value="Cancel">'
        "</form>"
    )


def mock_panopto_sign_in(*, accepted: bool = True) -> None:
    """The campus SSO bounce: Panopto's login page, the campus endpoint, Panopto again.

    The campus endpoint only vouches for a request carrying the Moodle session cookie.
    """
    login_url = f"{PANOPTO_URL}/Panopto/Pages/Auth/Login.aspx"
    sso_url = f"{BASE_URL}/blocks/panopto/SSO.php"

    def panopto_login(request: httpx.Request) -> httpx.Response:
        if "authCode" not in request.url.params:
            return httpx.Response(302, headers={"Location": f"{sso_url}?authCode=challenge"})
        if not accepted:
            return httpx.Response(200, text="<title>Sign in</title>")
        return httpx.Response(200, headers={"Set-Cookie": ".ASPXAUTH=signed-in; Path=/"})

    def campus_sso(request: httpx.Request) -> httpx.Response:
        if "MoodleSession" not in request.headers.get("cookie", ""):
            return httpx.Response(303, headers={"Location": f"{BASE_URL}/login/index.php"})
        return httpx.Response(303, headers={"Location": f"{login_url}?authCode=signed"})

    respx.get(login_url).mock(side_effect=panopto_login)
    respx.get(sso_url).mock(side_effect=campus_sso)
    respx.get(f"{BASE_URL}/login/index.php").mock(return_value=httpx.Response(200))
