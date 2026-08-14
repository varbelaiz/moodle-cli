"""Shared test fixtures for the anydoc plugin.

Self-contained rather than sharing the core suite's conftest: workspace members run
their tests independently, and this only needs a config-and-token environment, not the
core suite's full fixture set.
"""

from __future__ import annotations

import pytest

BASE_URL = "https://campus.example.edu"


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the developer's real .env and keyring out of the unit tests.

    Every test here fakes open_client directly rather than resolving a real token, but
    this stays as a safety net against a future test that forgets to.
    """
    monkeypatch.setattr("moodle_cli.config._find_dotenv", lambda: None)
    monkeypatch.setattr("moodle_cli.config._ENV_LOADED", False)
    for var in ("MOODLE_URL", "MOODLE_USER", "MOODLE_PASS", "MOODLE_TOKEN", "FIRECRAWL_KEY"):
        monkeypatch.delenv(var, raising=False)
