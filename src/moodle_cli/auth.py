"""Token minting and storage.

`login/token.php` answers failures with HTTP 200 and an ``error``/``errorcode`` body, so
success is decided by the presence of the ``token`` key and never by the status code.
"""

from __future__ import annotations

import httpx
import keyring
from keyring.errors import KeyringError

from moodle_cli.config import KEYRING_SERVICE, MOBILE_SERVICE, Config
from moodle_cli.errors import AuthError


def mint_token(
    base_url: str,
    username: str,
    password: str,
    *,
    service: str = MOBILE_SERVICE,
    client: httpx.Client | None = None,
) -> str:
    """Exchange credentials for a long-lived web-service token."""
    owned = client is None
    http = client or httpx.Client(timeout=30, follow_redirects=True)
    try:
        response = http.post(
            f"{base_url.rstrip('/')}/login/token.php",
            data={"username": username, "password": password, "service": service},
        )
        payload = response.json()
    finally:
        if owned:
            http.close()

    token = payload.get("token")
    if not token:
        code = payload.get("errorcode", "unknown")
        message = payload.get("error") or payload.get("message") or "Token request failed"
        raise AuthError(f"{message} [{code}]")
    return str(token)


class TokenStore:
    """Keyring-backed token storage, degrading to a no-op when no backend is available."""

    def __init__(self, service: str = KEYRING_SERVICE) -> None:
        self.service = service

    def get(self, key: str) -> str | None:
        try:
            return keyring.get_password(self.service, key)
        except KeyringError:
            return None

    def set(self, key: str, token: str) -> bool:
        try:
            keyring.set_password(self.service, key, token)
        except KeyringError:
            return False
        return True

    def delete(self, key: str) -> bool:
        try:
            keyring.delete_password(self.service, key)
        except KeyringError:
            return False
        return True


def resolve_token(
    config: Config,
    *,
    store: TokenStore | None = None,
    allow_mint: bool = True,
) -> str:
    """Find a usable token.

    Precedence is explicit-override first: ``MOODLE_TOKEN`` beats the keyring, so setting it
    to try another account does what it looks like it does. Minting is the last resort and
    is the only step that needs a password.
    """
    if config.token:
        return config.token

    store = store or TokenStore()
    stored = store.get(config.keyring_key)
    if stored:
        return stored

    if not allow_mint:
        raise AuthError("No stored token. Run `moodle auth login` first.")

    if not (config.username and config.password):
        raise AuthError(
            "No stored token and no credentials to mint one with. "
            "Run `moodle auth login`, or set MOODLE_USER and MOODLE_PASS."
        )

    token = mint_token(config.base_url, config.username, config.password)
    store.set(config.keyring_key, token)
    return token
