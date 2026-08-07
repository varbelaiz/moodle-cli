"""Guards on how plugins are declared, read straight from the pyproject files.

These read the source rather than installed metadata so a mistake fails in the pull request
that introduces it, not months later when someone tries to install the package. Every one
of them passes vacuously today: this release declares no plugins, and the point is that the
first one to be declared wrongly cannot land quietly.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

import pytest

from moodle_cli.plugins import AGGREGATE_EXTRAS, CORE_DISTRIBUTION, ENTRY_POINT_GROUP

ROOT = Path(__file__).resolve().parent.parent
PLUGIN_ROOT = ROOT / "plugins"

_REQUIREMENT_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def _name_of(requirement: str) -> str | None:
    """The distribution a requirement string names, ignoring its version specifier."""
    match = _REQUIREMENT_NAME.match(requirement)
    return match.group(1) if match else None


def _load(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = tomllib.loads(path.read_text(encoding="utf-8"))
    return data


def _core() -> dict[str, Any]:
    return _load(ROOT / "pyproject.toml")


def _plugin_manifests() -> list[tuple[str, dict[str, Any]]]:
    if not PLUGIN_ROOT.is_dir():
        return []
    return [
        (path.parent.name, _load(path)) for path in sorted(PLUGIN_ROOT.glob("*/pyproject.toml"))
    ]


def _single_package_extras() -> dict[str, str]:
    extras = _core()["project"].get("optional-dependencies", {})
    return {
        name: distribution
        for name, requirements in extras.items()
        if len(requirements) == 1
        and name not in AGGREGATE_EXTRAS
        and (distribution := _name_of(requirements[0])) is not None
    }


def test_every_workspace_plugin_is_reachable_through_an_extra() -> None:
    """A plugin directory with no extra is a package nobody can install."""
    declared = set(_single_package_extras().values())
    present = {manifest["project"]["name"] for _, manifest in _plugin_manifests()}

    assert present == declared


def test_a_plugins_directory_name_is_the_extra_that_installs_it() -> None:
    """`moodle plugins install NAME` names the extra, so the two must not drift."""
    by_distribution = {dist: extra for extra, dist in _single_package_extras().items()}

    for directory, manifest in _plugin_manifests():
        assert by_distribution.get(manifest["project"]["name"]) == directory


def test_an_aggregate_extra_is_exactly_the_union_of_the_others() -> None:
    """`all` that misses a plugin is a promise the name does not keep."""
    extras = _core()["project"].get("optional-dependencies", {})
    singles = set(_single_package_extras().values())

    for name in AGGREGATE_EXTRAS & extras.keys():
        members = {_name_of(requirement) for requirement in extras[name]}
        assert members == singles


def test_every_plugin_declares_one_entry_point_named_for_its_extra() -> None:
    for directory, manifest in _plugin_manifests():
        entry_points = manifest["project"].get("entry-points", {}).get(ENTRY_POINT_GROUP, {})
        assert list(entry_points) == [directory]


@pytest.mark.parametrize("bound", ["<", "=="])
def test_every_plugin_pins_an_upper_bound_on_the_core(bound: str) -> None:
    """uv publishes a workspace member with an unbounded core dependency.

    Without a bound written by hand, the released plugin claims to work against every
    future core release, including the one that changes the plugin contract.
    """
    for directory, manifest in _plugin_manifests():
        requirements = [
            requirement
            for requirement in manifest["project"]["dependencies"]
            if _name_of(requirement) == CORE_DISTRIBUTION
        ]
        assert requirements, f"{directory} does not depend on {CORE_DISTRIBUTION}"
        assert any(bound in requirement for requirement in requirements), (
            f"{directory} does not bound {CORE_DISTRIBUTION} from above"
        )


def test_every_plugin_requires_the_same_python_as_the_core() -> None:
    """A plugin that accepts an older Python than the core cannot actually run on it."""
    expected = _core()["project"]["requires-python"]

    for directory, manifest in _plugin_manifests():
        assert manifest["project"]["requires-python"] == expected, directory
