"""Tests for the one way to get a configured client."""

from __future__ import annotations

import pytest

from moodle_cli.errors import AuthError
from moodle_cli.session import open_client
from tests.conftest import BASE_URL


@pytest.mark.usefixtures("configured_env")
def test_open_client_carries_the_resolved_token() -> None:
    """The token rides on the client, which is why this returns one thing and not a pair.

    Downloading from pluginfile.php needs the raw token, and reaching for it here is what
    lets every caller take a client and nothing else.
    """
    client = open_client()

    assert client.token == "test-token"
    assert client.base_url == BASE_URL


@pytest.mark.usefixtures("configured_env")
def test_open_client_closes_its_transport_on_exit() -> None:
    """It hands back an unentered client, so `with` has to close the transport itself."""
    with open_client() as client:
        assert not client._http.is_closed

    assert client._http.is_closed


def test_open_client_refuses_to_mint_when_asked_not_to(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reporting on a session must not create one: `auth status` would prompt otherwise."""
    monkeypatch.setenv("MOODLE_URL", BASE_URL)
    monkeypatch.setattr("moodle_cli.auth.TokenStore.get", lambda self, key: None)

    with pytest.raises(AuthError, match="No stored token"):
        open_client(allow_mint=False)
