"""Shared test fixtures for the panopto plugin.

Self-contained rather than sharing the core suite's conftest: workspace members run
their tests independently. Registers its own ``--live`` option/skip machinery because
this plugin -- unlike anydoc -- has a live suite of its own.
"""

from __future__ import annotations

import pytest

BASE_URL = "https://campus.example.edu"
PANOPTO_HOST = "campus.hosted.panopto.com"
PANOPTO_URL = f"https://{PANOPTO_HOST}"


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
def isolated_env(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    """Keep the developer's real .env and keyring out of the unit tests.

    Every non-live test here fakes its own client/session rather than resolving real
    credentials, but this stays as a safety net against a future test that forgets to.
    """
    if "live" in request.keywords:
        return
    monkeypatch.setattr("moodle_cli.config._find_dotenv", lambda: None)
    monkeypatch.setattr("moodle_cli.config._ENV_LOADED", False)
    for var in ("MOODLE_URL", "MOODLE_USER", "MOODLE_PASS", "MOODLE_TOKEN"):
        monkeypatch.delenv(var, raising=False)


def recording_link(delivery_id: str, name: str, *, host: str = PANOPTO_HOST) -> str:
    """One `block_panopto_get_content`-style anchor, the shape recordings.py parses."""
    return (
        f"<a href='https://{host}/Panopto/Pages/Viewer.aspx?id={delivery_id}&instance=x'>{name}</a>"
    )


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


def lti_launch_html(action: str, fields: dict[str, str]) -> str:
    inputs = "".join(
        f'<input type="hidden" name="{name}" value="{value}"/>' for name, value in fields.items()
    )
    return (
        f'<form name="ltiLaunchForm" action="{action}" method="post">{inputs}</form>'
        "<script>document.ltiLaunchForm.submit();</script>"
    )
