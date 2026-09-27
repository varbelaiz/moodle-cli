"""Configuration and credential resolution.

Credentials come from the environment (optionally seeded by a .env file). The password is
only ever needed to mint a token; once one is stored in the keyring it can be removed.

The campus URL can also be saved to a per-user file, so a tool installed on the PATH -- or
an MCP server launched from an arbitrary directory -- reaches the same campus the keyring
token belongs to without a .env nearby.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from moodle_cli.errors import ConfigError

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


def _config_dir() -> Path:
    """The per-user settings directory, following each platform's convention."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "moodle-cli"
    if sys.platform == "win32":
        root = os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming"
    else:
        root = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(root) / "moodle-cli"


def _settings_path() -> Path:
    return _config_dir() / "config.json"


def saved_url() -> str | None:
    """The campus URL saved by `save_url`, or None when there is none to read.

    An unreadable or malformed file counts as none: the resulting error points at
    `auth login`, which writes the file afresh.
    """
    try:
        settings = json.loads(_settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    url = settings.get("url") if isinstance(settings, dict) else None
    return url if isinstance(url, str) and url else None


def save_url(url: str) -> None:
    """Persist the campus URL for every later run, from any directory."""
    path = _settings_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"url": url}), encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"Could not save the campus URL to {path}: {exc}") from exc


def load_config(base_url: str | None = None) -> Config:
    """Resolve configuration, taking the campus URL from the first source that has one.

    Precedence is `base_url`, then MOODLE_URL (environment or .env), then the saved URL.
    The variable beats the saved file so it stays a per-shell override, e.g. to point a
    checkout at another campus without touching what an installed tool uses.
    """
    ensure_env_loaded()
    url = base_url or os.environ.get("MOODLE_URL") or saved_url()
    if not url:
        raise ConfigError(
            "No campus URL configured. Set MOODLE_URL in the environment or a .env file."
        )
    return Config(
        base_url=url.rstrip("/"),
        username=os.environ.get("MOODLE_USER"),
        password=os.environ.get("MOODLE_PASS"),
        token=os.environ.get("MOODLE_TOKEN"),
    )
