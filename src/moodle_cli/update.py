"""Checking this installation's version against the latest GitHub release.

There is no package index in the loop: "moodle-cli" on PyPI is a different, unrelated
project, so releases live entirely on GitHub and installs point at the repo directly (see
`toolenv.git_spec`).
"""

from __future__ import annotations

import httpx
from packaging.version import InvalidVersion, Version

from moodle_cli.errors import MoodleError
from moodle_cli.plugins import CORE_REPO_URL

# Derived rather than restated, so a repo rename only has one constant to change.
_API_URL = CORE_REPO_URL.replace("github.com/", "api.github.com/repos/", 1) + "/releases/latest"
_TIMEOUT = 10.0


def latest_release() -> str:
    """The tag name of the most recent GitHub release, e.g. "v0.2.0"."""
    try:
        response = httpx.get(_API_URL, headers={"User-Agent": "moodle-cli"}, timeout=_TIMEOUT)
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
