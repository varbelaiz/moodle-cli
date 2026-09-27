"""Tests for keeping the campus's device-trust cookie in the keyring."""

from __future__ import annotations

import time

import httpx
import keyring
from moodle_cli_panopto import device_trust

from conftest import BASE_URL


def _cookie(expires: int) -> httpx.Cookies:
    cookies = httpx.Cookies()
    cookies.set("MFA_TOKEN_42", "trust-secret", domain="campus.example.edu", path="/")
    next(iter(cookies.jar)).expires = expires
    return cookies


def test_a_saved_cookie_loads_back_with_its_name_value_and_scope() -> None:
    device_trust.save(BASE_URL, next(iter(_cookie(int(time.time()) + 86400).jar)))

    loaded = device_trust.load(BASE_URL)

    assert loaded is not None
    assert (loaded.name, loaded.value, loaded.domain, loaded.path) == (
        "MFA_TOKEN_42",
        "trust-secret",
        "campus.example.edu",
        "/",
    )


def test_a_cookie_about_to_expire_is_not_loaded() -> None:
    """The campus locks the trust factor for a session presenting an expired cookie."""
    device_trust.save(BASE_URL, next(iter(_cookie(int(time.time()) + 60).jar)))

    assert device_trust.load(BASE_URL) is None


def test_nothing_stored_loads_as_none() -> None:
    assert device_trust.load(BASE_URL) is None


def test_a_malformed_entry_loads_as_none() -> None:
    keyring.set_password(device_trust.KEYRING_SERVICE, BASE_URL, "not json")

    assert device_trust.load(BASE_URL) is None
