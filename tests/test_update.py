"""Tests for `update.latest_release`.

The GitHub Releases API is the only network call this package makes without a Moodle
campus in the loop, so it gets its own boundary test rather than reusing conftest's
Moodle-shaped respx helpers.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from moodle_cli.errors import MoodleError
from moodle_cli.update import _API_URL, latest_release


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
