"""Tests for `update.latest_release` and `update.pending_update`.

The GitHub Releases API is the only network call this package makes without a Moodle
campus in the loop, so it gets its own boundary test rather than reusing conftest's
Moodle-shaped respx helpers.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx
import pytest
import respx

from moodle_cli.errors import MoodleError
from moodle_cli.update import (
    _API_URL,
    _CHECK_INTERVAL,
    DISABLE_ENV,
    _cache_path,
    latest_release,
    pending_update,
)


@respx.mock
def test_latest_release_returns_the_tag_name() -> None:
    respx.get(_API_URL).mock(return_value=httpx.Response(200, json={"tag_name": "v0.2.0"}))
    assert latest_release() == "v0.2.0"


@respx.mock
def test_latest_release_raises_when_nothing_has_been_released_yet() -> None:
    respx.get(_API_URL).mock(return_value=httpx.Response(404, json={"message": "Not Found"}))
    with pytest.raises(MoodleError, match="No release has been published"):
        latest_release()


@respx.mock
def test_latest_release_raises_on_a_github_error_response() -> None:
    respx.get(_API_URL).mock(return_value=httpx.Response(500, json={"message": "oops"}))
    with pytest.raises(MoodleError, match="500"):
        latest_release()


@respx.mock
def test_latest_release_raises_on_a_network_failure() -> None:
    respx.get(_API_URL).mock(side_effect=httpx.ConnectError("no route"))
    with pytest.raises(MoodleError, match="Could not reach GitHub"):
        latest_release()


@respx.mock
def test_latest_release_raises_when_the_response_has_no_tag_name() -> None:
    respx.get(_API_URL).mock(return_value=httpx.Response(200, json={}))
    with pytest.raises(MoodleError, match="tag_name"):
        latest_release()


# -- pending_update ----------------------------------------------------------------------


@pytest.fixture
def cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Enable the check, with its cache under a tmp dir."""
    monkeypatch.delenv(DISABLE_ENV)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    return _cache_path()


def _write_cache(path: Path, *, latest: str | None, age: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"checked_at": time.time() - age, "latest": latest}))


@respx.mock
def test_pending_update_announces_a_newer_release(cache: Path) -> None:
    respx.get(_API_URL).mock(return_value=httpx.Response(200, json={"tag_name": "v0.2.0"}))
    assert pending_update("0.1.0") == "v0.2.0"


@respx.mock
def test_pending_update_is_silent_when_current(cache: Path) -> None:
    respx.get(_API_URL).mock(return_value=httpx.Response(200, json={"tag_name": "v0.2.0"}))
    assert pending_update("0.2.0") is None


@respx.mock
def test_pending_update_asks_github_at_most_once_per_interval(cache: Path) -> None:
    route = respx.get(_API_URL).mock(return_value=httpx.Response(200, json={"tag_name": "v0.2.0"}))
    pending_update("0.1.0")
    assert pending_update("0.1.0") == "v0.2.0"
    assert route.call_count == 1


@respx.mock
def test_pending_update_asks_again_once_the_interval_has_passed(cache: Path) -> None:
    _write_cache(cache, latest="v0.2.0", age=_CHECK_INTERVAL + 1)
    respx.get(_API_URL).mock(return_value=httpx.Response(200, json={"tag_name": "v0.3.0"}))
    assert pending_update("0.1.0") == "v0.3.0"


@respx.mock
def test_pending_update_remembers_a_failed_check(cache: Path) -> None:
    route = respx.get(_API_URL).mock(side_effect=httpx.ConnectError("no route"))
    assert pending_update("0.1.0") is None
    assert pending_update("0.1.0") is None
    assert route.call_count == 1


@respx.mock
def test_pending_update_recovers_from_a_corrupt_cache(cache: Path) -> None:
    cache.parent.mkdir(parents=True)
    cache.write_text("not json")
    respx.get(_API_URL).mock(return_value=httpx.Response(200, json={"tag_name": "v0.2.0"}))
    assert pending_update("0.1.0") == "v0.2.0"


def test_pending_update_is_silent_on_an_unparseable_tag(cache: Path) -> None:
    _write_cache(cache, latest="nightly", age=0)
    assert pending_update("0.1.0") is None


@respx.mock
def test_pending_update_never_reaches_the_network_when_disabled(
    cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(DISABLE_ENV, "1")
    route = respx.get(_API_URL)
    assert pending_update("0.1.0") is None
    assert not route.called
