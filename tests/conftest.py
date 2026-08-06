"""Shared test fixtures.

Fixtures are synthetic but shape-accurate: they reproduce the quirks the real campus
returns (null ``filepath``, ``isexternalfile`` on bibliography files, doubled extensions)
without committing real classmates' names or email addresses to the repository.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
BASE_URL = "https://campus.example.edu"
REST_URL = f"{BASE_URL}/webservice/rest/server.php"
TOKEN_URL = f"{BASE_URL}/login/token.php"


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


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    """Keep the developer's real .env and keyring out of the unit tests.

    Without this, a .env in the repo root would silently supply real credentials.
    """
    if "live" in request.keywords:
        return
    monkeypatch.setattr("moodle_cli.config._find_dotenv", lambda: None)
    monkeypatch.setattr("moodle_cli.config._ENV_LOADED", False)
    for var in ("MOODLE_URL", "MOODLE_USER", "MOODLE_PASS", "MOODLE_TOKEN"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def courses_payload() -> dict[str, Any]:
    payload: dict[str, Any] = load_fixture("courses.json")
    return payload


@pytest.fixture
def contents_payload() -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = load_fixture("contents.json")
    return payload


@pytest.fixture
def participants_payload() -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = load_fixture("participants.json")
    return payload


@pytest.fixture
def forums_payload() -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = load_fixture("forums.json")
    return payload


@pytest.fixture
def discussions_payload() -> dict[str, Any]:
    payload: dict[str, Any] = load_fixture("discussions.json")
    return payload


@pytest.fixture
def assignments_payload() -> dict[str, Any]:
    payload: dict[str, Any] = load_fixture("assignments.json")
    return payload


@pytest.fixture
def submission_status_payload() -> dict[str, Any]:
    payload: dict[str, Any] = load_fixture("submission_status.json")
    return payload


@pytest.fixture
def grades_overview_payload() -> dict[str, Any]:
    payload: dict[str, Any] = load_fixture("grades_overview.json")
    return payload


@pytest.fixture
def grade_items_payload() -> dict[str, Any]:
    payload: dict[str, Any] = load_fixture("grade_items.json")
    return payload


@pytest.fixture
def site_info_payload() -> dict[str, Any]:
    return {"userid": 63643, "functions": []}


@pytest.fixture
def quizzes_payload() -> dict[str, Any]:
    payload: dict[str, Any] = load_fixture("quizzes.json")
    return payload


@pytest.fixture
def quiz_attempts_payload() -> dict[str, Any]:
    payload: dict[str, Any] = load_fixture("quiz_attempts.json")
    return payload


@pytest.fixture
def quiz_best_grade_payload() -> dict[str, Any]:
    payload: dict[str, Any] = load_fixture("quiz_best_grade.json")
    return payload


@pytest.fixture
def tmp_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.chdir(tmp_path)
    yield tmp_path
