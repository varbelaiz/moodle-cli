"""Keeping the campus's "trust this device" cookie across runs.

Completing MFA with the trust box ticked makes the campus issue a cookie that passes MFA
on every later password login until it expires. It is a credential, so it lives in the
keyring beside the web-service token, under a service of its own.
"""

from __future__ import annotations

import json
import time
from http.cookiejar import Cookie

import httpx

from moodle_cli.auth import TokenStore

KEYRING_SERVICE = "moodle-cli-mfa-trust"
#: The campus locks the trust factor for a session that presents an expired cookie, so
#: one this close to expiry is dropped rather than sent.
_EXPIRY_MARGIN = 3600


def load(key: str, store: TokenStore | None = None) -> Cookie | None:
    """The stored trust cookie for KEY, or None when there is none still valid."""
    raw = (store or TokenStore(KEYRING_SERVICE)).get(key)
    if not raw:
        return None
    try:
        saved = json.loads(raw)
        name, value, domain, path = (saved[k] for k in ("name", "value", "domain", "path"))
        expires = int(saved["expires"])
    except (ValueError, KeyError, TypeError):
        return None
    if expires <= time.time() + _EXPIRY_MARGIN:
        return None
    cookies = httpx.Cookies()
    cookies.set(name, value, domain=domain, path=path)
    return next(iter(cookies.jar))


def save(key: str, cookie: Cookie, store: TokenStore | None = None) -> None:
    """Store COOKIE for KEY, replacing any earlier one. A no-op without a keyring."""
    saved = {
        "name": cookie.name,
        "value": cookie.value,
        "domain": cookie.domain,
        "path": cookie.path,
        "expires": cookie.expires,
    }
    (store or TokenStore(KEYRING_SERVICE)).set(key, json.dumps(saved))
