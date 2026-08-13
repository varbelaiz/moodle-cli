"""Configuration and credential resolution.

Credentials come from the environment (optionally seeded by a .env file). The password is
only ever needed to mint a token; once one is stored in the keyring it can be removed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

MOBILE_SERVICE = "moodle_mobile_app"
KEYRING_SERVICE = "moodle-cli"

_ENV_LOADED = False


def ensure_env_loaded() -> None:
    """Load a .env from the cwd (or any parent) exactly once.

    Public so callers outside `load_config` -- e.g. a plugin reading its own env var --
    can rely on the same .env without going through Moodle-specific config.

    Skips the call to `load_dotenv` entirely when `_find_dotenv` finds nothing, rather
    than calling `load_dotenv(None)`: passed `None`, python-dotenv falls back to its own
    upward search from the caller's frame, bypassing `_find_dotenv` -- which a test that
    monkeypatches `_find_dotenv` to isolate itself from a developer's real .env would not
    expect.
    """
    global _ENV_LOADED
    if not _ENV_LOADED:
        dotenv_path = _find_dotenv()
        if dotenv_path is not None:
            load_dotenv(dotenv_path)
        _ENV_LOADED = True


def _find_dotenv() -> Path | None:
    for directory in [Path.cwd(), *Path.cwd().parents]:
        candidate = directory / ".env"
        if candidate.is_file():
            return candidate
    return None


@dataclass(frozen=True)
class Config:
    base_url: str
    username: str | None = None
    password: str | None = None
    token: str | None = None

    @property
    def keyring_key(self) -> str:
        """Keyed on the campus alone, deliberately.

        Including the username would break the common flow: `auth login` learns it from a
        prompt while `resolve_token` reads it from MOODLE_USER, so a token stored after an
        interactive login would be filed under a key nothing later looks up. One account
        per campus is the only case this tool needs.
        """
        return self.base_url


def load_config(base_url: str | None = None) -> Config:
    ensure_env_loaded()
    url = base_url or os.environ.get("MOODLE_URL")
    if not url:
        raise ValueError(
            "No campus URL configured. Set MOODLE_URL in the environment or a .env file."
        )
    return Config(
        base_url=url.rstrip("/"),
        username=os.environ.get("MOODLE_USER"),
        password=os.environ.get("MOODLE_PASS"),
        token=os.environ.get("MOODLE_TOKEN"),
    )
