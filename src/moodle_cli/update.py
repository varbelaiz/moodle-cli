"""Checking this installation's version against the latest GitHub release.

There is no package index in the loop: "moodle-cli" on PyPI is a different, unrelated
project, so releases live entirely on GitHub and installs point at the repo directly (see
`toolenv.git_spec`).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx
from packaging.version import InvalidVersion, Version

from moodle_cli.config import ensure_env_loaded
from moodle_cli.errors import MoodleError
from moodle_cli.plugins import CORE_REPO_URL

# Derived rather than restated, so a repo rename only has one constant to change.
_API_URL = CORE_REPO_URL.replace("github.com/", "api.github.com/repos/", 1) + "/releases/latest"
_TIMEOUT = 10.0

DISABLE_ENV = "MOODLE_NO_UPDATE_CHECK"
_CHECK_INTERVAL = 24 * 60 * 60
# Short, because this check runs unasked at the end of an ordinary command.
_NOTICE_TIMEOUT = 2.0


def latest_release(timeout: float = _TIMEOUT) -> str:
    """The tag name of the most recent GitHub release, e.g. "v0.2.0"."""
    try:
        response = httpx.get(_API_URL, headers={"User-Agent": "moodle-cli"}, timeout=timeout)
    except httpx.HTTPError as exc:
        raise MoodleError(f"Could not reach GitHub to check for updates: {exc}") from exc

    if response.status_code == 404:
        raise MoodleError(f"No release has been published yet at {CORE_REPO_URL}.")
    if response.is_error:
        raise MoodleError(f"GitHub returned {response.status_code} checking for updates.")

    tag_name = response.json().get("tag_name")
    if not tag_name:
        raise MoodleError("GitHub's latest-release response had no tag_name.")
    return str(tag_name)


def is_newer(tag: str, current: str) -> bool:
    """Whether release `tag` (e.g. "v0.2.0") is newer than the installed `current` version."""
    try:
        parsed_tag = Version(tag.removeprefix("v"))
    except InvalidVersion as exc:
        raise MoodleError(f"{tag!r} is not a valid release tag: {exc}") from exc
    return parsed_tag > _parse_current(current)


def is_exact_release(version: str) -> bool:
    """Whether `version` is an exact tagged release rather than a distance-from-tag build.

    A hatch-vcs version off a tag carries a `+g<hash>` local segment. Only when this is
    True does `v{version}` name a real git tag.
    """
    return _parse_current(version).local is None


def _parse_current(version: str) -> Version:
    """The installed `version` parsed, blaming the local install rather than a release tag."""
    try:
        return Version(version)
    except InvalidVersion as exc:
        raise MoodleError(f"{version!r} is not a valid installed version: {exc}") from exc


def pending_update(current: str) -> str | None:
    """The release tag newer than `current` worth announcing, or None. Never raises.

    GitHub is asked at most once per `_CHECK_INTERVAL`; every other run reads the answer
    back from disk.
    """
    ensure_env_loaded()
    if os.environ.get(DISABLE_ENV):
        return None
    try:
        latest = _latest_known()
        return latest if latest is not None and is_newer(latest, current) else None
    except (MoodleError, OSError):
        return None


def _latest_known() -> str | None:
    path = _cache_path()
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
        if time.time() - cached["checked_at"] < _CHECK_INTERVAL:
            return cached["latest"]  # type: ignore[no-any-return]
    except (OSError, ValueError, KeyError, TypeError):
        pass

    latest: str | None
    try:
        latest = latest_release(timeout=_NOTICE_TIMEOUT)
    except MoodleError:
        latest = None
    # A failed check is recorded too, so an offline machine pays the timeout once per
    # interval rather than on every command.
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"checked_at": time.time(), "latest": latest}), encoding="utf-8")
    return latest


def _cache_path() -> Path:
    root = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(root) / "moodle-cli" / "update-check.json"
