"""Auth tests.

The campus answers a bad login with HTTP 200 and an error body, so the interesting case
is not a 401 but a successful-looking response carrying a failure.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from moodle_cli.auth import TokenStore, mint_token, resolve_token
from moodle_cli.config import Config
from moodle_cli.errors import AuthError
from tests.conftest import BASE_URL, TOKEN_URL


class FakeStore(TokenStore):
    def __init__(self, initial: dict[str, str] | None = None) -> None:
        self.data = dict(initial or {})

    def get(self, key: str) -> str | None:
        return self.data.get(key)

    def set(self, key: str, token: str) -> bool:
        self.data[key] = token
        return True

    def delete(self, key: str) -> bool:
        return self.data.pop(key, None) is not None


@respx.mock
def test_mint_token_returns_token() -> None:
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"token": "abc123", "privatetoken": None})
    )
    assert mint_token(BASE_URL, "user", "pass") == "abc123"


@respx.mock
def test_mint_token_raises_on_http_200_error_body() -> None:
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            200, json={"error": "Invalid login, please try again", "errorcode": "invalidlogin"}
        )
    )
    with pytest.raises(AuthError, match="invalidlogin"):
        mint_token(BASE_URL, "user", "wrong")


@respx.mock
def test_mint_token_raises_when_service_disabled() -> None:
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            200, json={"error": "Web services are disabled", "errorcode": "enablewsdescription"}
        )
    )
    with pytest.raises(AuthError, match="enablewsdescription"):
        mint_token(BASE_URL, "user", "pass")


def test_resolve_token_prefers_explicit_env_token_over_keyring() -> None:
    config = Config(base_url=BASE_URL, username="user", token="from-env")
    store = FakeStore({config.keyring_key: "from-keyring"})
    assert resolve_token(config, store=store) == "from-env"


def test_resolve_token_falls_back_to_keyring() -> None:
    config = Config(base_url=BASE_URL, username="user")
    store = FakeStore({config.keyring_key: "from-keyring"})
    assert resolve_token(config, store=store) == "from-keyring"


@respx.mock
def test_resolve_token_mints_and_caches_when_nothing_stored() -> None:
    route = respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json={"token": "minted"}))
    config = Config(base_url=BASE_URL, username="user", password="pass")
    store = FakeStore()

    assert resolve_token(config, store=store) == "minted"
    assert store.data[config.keyring_key] == "minted"
    assert route.call_count == 1


def test_keyring_key_ignores_the_username() -> None:
    """Regression: `auth login` learns the username from a prompt while `resolve_token`
    reads it from MOODLE_USER. If the key depended on it, an interactive login would file
    the token where nothing later looks for it."""
    stored_after_prompt = Config(base_url=BASE_URL, username="45822770").keyring_key
    looked_up_without_env = Config(base_url=BASE_URL, username=None).keyring_key
    assert stored_after_prompt == looked_up_without_env


def test_resolve_token_refuses_to_mint_when_disallowed() -> None:
    config = Config(base_url=BASE_URL, username="user", password="pass")
    with pytest.raises(AuthError, match="auth login"):
        resolve_token(config, store=FakeStore(), allow_mint=False)


def test_resolve_token_reports_missing_credentials() -> None:
    config = Config(base_url=BASE_URL, username="user")
    with pytest.raises(AuthError, match="MOODLE_USER"):
        resolve_token(config, store=FakeStore())
