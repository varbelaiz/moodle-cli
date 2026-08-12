"""Tests for the `moodle plugins` command group.

The packaging commands are faked at the boundary: what matters is the argv this builds,
because that argv is what decides whether someone's hand-injected packages survive.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from moodle_cli import cli, toolenv
from moodle_cli.plugins import CatalogEntry
from moodle_cli.toolenv import Environment, injected_packages

runner = CliRunner()


def _entry(
    name: str,
    *,
    official: bool = True,
    installed: bool = False,
    version: str | None = None,
    summary: str | None = None,
    mounted_as: str | None = None,
    tools: tuple[str, ...] = (),
    problem: str | None = None,
) -> CatalogEntry:
    return CatalogEntry(
        name=name,
        distribution=f"moodle-cli-{name}",
        official=official,
        installed=installed,
        version=version,
        summary=summary,
        mounted_as=mounted_as,
        tools=tools,
        problem=problem,
    )


@pytest.fixture
def catalog_of(monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    """Pin the catalog, so these tests do not depend on what this release declares."""

    def install(*entries: CatalogEntry) -> None:
        monkeypatch.setattr(cli, "catalog", lambda: entries)
        monkeypatch.setattr(
            cli,
            "installed_extras",
            lambda: frozenset(e.name for e in entries if e.official and e.installed),
        )
        # Pinned for the same reason as the other two: read for real, this returns whatever
        # extras this checkout happens to declare, so a test would prove something
        # different here than in an environment with a different set of plugins.
        monkeypatch.setattr(
            cli,
            "extra_distributions",
            lambda: {e.name: e.distribution for e in entries if e.official},
        )

    return install


@pytest.fixture
def recorded(monkeypatch: pytest.MonkeyPatch) -> list[Sequence[str]]:
    """Record the packaging commands instead of running them."""
    calls: list[Sequence[str]] = []

    def fake_run(argv: Sequence[str], *, capture: bool) -> str:
        calls.append(argv)
        return ""

    monkeypatch.setattr(cli, "run", fake_run)
    return calls


def _environment(
    monkeypatch: pytest.MonkeyPatch, kind: str, *, injected: list[str] | None = None
) -> None:
    monkeypatch.setattr(
        cli,
        "detect",
        lambda: Environment(kind, Path("/env/bin/python"), "/usr/bin/uv"),  # type: ignore[arg-type]
    )
    monkeypatch.setattr(cli, "injected_packages", lambda uv: injected)


# -- list ----------------------------------------------------------------------------


def test_plugins_list_shows_a_known_plugin_that_is_not_installed(
    catalog_of: Callable[..., None],
) -> None:
    """An uninstalled plugin has no description to show, so it shows how to get it."""
    catalog_of(_entry("anydoc"))

    result = runner.invoke(cli.app, ["plugins", "list"])

    assert result.exit_code == 0
    assert "anydoc" in result.stdout
    assert "available" in result.stdout
    assert "moodle plugins install NAME" in result.stdout


def test_plugins_list_json_names_the_commands_and_tools_a_plugin_adds(
    catalog_of: Callable[..., None],
) -> None:
    catalog_of(
        _entry(
            "anydoc",
            installed=True,
            version="0.1.0",
            summary="Convert documents.",
            mounted_as="anydoc",
            tools=("anydoc_convert",),
        )
    )

    result = runner.invoke(cli.app, ["plugins", "list", "--json"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == [
        {
            "name": "anydoc",
            "distribution": "moodle-cli-anydoc",
            "official": True,
            "status": "installed",
            "version": "0.1.0",
            "summary": "Convert documents.",
            "command_group": "anydoc",
            "mcp_tools": ["anydoc_convert"],
            "problem": None,
        }
    ]


def test_plugins_list_reports_an_installed_plugin_that_was_rejected(
    catalog_of: Callable[..., None],
) -> None:
    """A plugin that is present but unusable must not read as merely absent."""
    catalog_of(_entry("broken", installed=True, version="0.1.0", problem="it failed to load"))

    result = runner.invoke(cli.app, ["plugins", "list"])

    assert result.exit_code == 0
    assert "error" in result.stdout
    assert "it failed to load" in result.stderr


def test_plugins_list_says_so_when_the_release_declares_no_plugins(
    catalog_of: Callable[..., None],
) -> None:
    catalog_of()

    result = runner.invoke(cli.app, ["plugins", "list"])

    assert result.exit_code == 0
    assert "No plugins in the catalog" in result.stdout


def test_plugins_list_shows_a_third_party_plugin_it_cannot_install(
    catalog_of: Callable[..., None],
) -> None:
    """A group appearing in --help from nowhere is what this command exists to explain."""
    catalog_of(_entry("demo", official=False, installed=True, version="0.1.0", mounted_as="demo"))

    result = runner.invoke(cli.app, ["plugins", "list"])

    assert result.exit_code == 0
    assert "third-party" in result.stdout


def test_plugins_list_surfaces_a_third_party_plugin_that_was_rejected(
    catalog_of: Callable[..., None],
) -> None:
    """Otherwise a skipped plugin is invisible, and its warning has nowhere to be read."""
    catalog_of(_entry("demo", official=False, installed=True, problem="it failed to load"))

    result = runner.invoke(cli.app, ["plugins", "list"])

    assert result.exit_code == 0
    assert "it failed to load" in result.stderr


# -- install -------------------------------------------------------------------------


def test_plugins_install_says_a_third_party_plugin_is_not_its_to_manage(
    catalog_of: Callable[..., None], recorded: list[Sequence[str]]
) -> None:
    """`No such plugin` would be a lie about something the user can see in `list`."""
    catalog_of(_entry("demo", official=False, installed=True, version="0.1.0"))

    result = runner.invoke(cli.app, ["plugins", "uninstall", "demo"])

    assert result.exit_code == 1
    assert "third-party plugin" in result.stderr
    assert "uv pip uninstall moodle-cli-demo" in result.stderr
    assert recorded == []


def test_plugins_install_rejects_an_unknown_name(catalog_of: Callable[..., None]) -> None:
    catalog_of(_entry("anydoc"))

    result = runner.invoke(cli.app, ["plugins", "install", "nope"])

    assert result.exit_code == 1
    assert "No such plugin" in result.stderr


def test_plugins_install_is_a_no_op_when_it_is_already_there(
    catalog_of: Callable[..., None], recorded: list[Sequence[str]]
) -> None:
    catalog_of(_entry("anydoc", installed=True, version="0.1.0"))

    result = runner.invoke(cli.app, ["plugins", "install", "anydoc"])

    assert result.exit_code == 0
    assert recorded == []


def test_plugins_install_preserves_packages_injected_by_hand(
    monkeypatch: pytest.MonkeyPatch, catalog_of: Callable[..., None], recorded: list[Sequence[str]]
) -> None:
    """`--with` replaces the injected set, so anything not restated is silently removed."""
    catalog_of(_entry("anydoc"))
    _environment(monkeypatch, "uv-tool", injected=["some-unrelated-tool==1.2"])

    result = runner.invoke(cli.app, ["plugins", "install", "anydoc"])

    assert result.exit_code == 0
    assert list(recorded[0]) == [
        "/usr/bin/uv",
        "tool",
        "install",
        "--reinstall",
        "moodle-cli[anydoc]",
        "--with",
        "some-unrelated-tool==1.2",
    ]


def test_plugins_install_carries_the_extras_already_present(
    monkeypatch: pytest.MonkeyPatch, catalog_of: Callable[..., None], recorded: list[Sequence[str]]
) -> None:
    """Reinstalling with only the new extra would uninstall the ones already there."""
    catalog_of(_entry("anydoc", installed=True, version="0.1.0"), _entry("panopto"))
    _environment(monkeypatch, "uv-tool", injected=[])

    result = runner.invoke(cli.app, ["plugins", "install", "panopto"])

    assert result.exit_code == 0
    assert "moodle-cli[anydoc,panopto]" in recorded[0]


def test_plugins_install_does_not_restate_a_plugin_uv_reports_as_injected(
    monkeypatch: pytest.MonkeyPatch, catalog_of: Callable[..., None], recorded: list[Sequence[str]]
) -> None:
    """A plugin someone injected by hand becomes an extra rather than appearing twice."""
    catalog_of(_entry("anydoc", installed=True, version="0.1.0"), _entry("panopto"))
    _environment(monkeypatch, "uv-tool", injected=["moodle-cli-anydoc==0.1.0"])

    result = runner.invoke(cli.app, ["plugins", "install", "panopto"])

    assert result.exit_code == 0
    assert "--with" not in recorded[0]


def test_plugins_install_keeps_an_injected_third_party_plugin(
    monkeypatch: pytest.MonkeyPatch, catalog_of: Callable[..., None], recorded: list[Sequence[str]]
) -> None:
    """A third-party plugin is in the catalog but is not an extra, so it has to stay a --with.

    `catalog()` lists third-party plugins on purpose, so filtering the injected set against
    the whole catalog drops them. They cannot come back as an extra either, since
    `installed_extras()` reports only official ones — so dropping them here uninstalls
    them, which is the one outcome the abort above exists to prevent.
    """
    catalog_of(
        _entry("anydoc"),
        _entry("panopto", official=False, installed=True, version="0.2.0"),
    )
    _environment(monkeypatch, "uv-tool", injected=["moodle-cli-panopto==0.2.0"])

    result = runner.invoke(cli.app, ["plugins", "install", "anydoc"])

    assert result.exit_code == 0
    assert "moodle-cli-panopto==0.2.0" in recorded[0], (
        "a third-party plugin was dropped from the rebuilt install command"
    )


def test_plugins_install_aborts_when_the_injected_set_cannot_be_read(
    monkeypatch: pytest.MonkeyPatch, catalog_of: Callable[..., None], recorded: list[Sequence[str]]
) -> None:
    """Losing someone's injected packages in silence is worse than refusing to act."""
    catalog_of(_entry("anydoc"))
    _environment(monkeypatch, "uv-tool", injected=None)

    result = runner.invoke(cli.app, ["plugins", "install", "anydoc"])

    assert result.exit_code == 1
    assert "Could not read the packages injected" in result.stderr
    assert recorded == []


def test_plugins_install_refuses_to_touch_a_development_checkout(
    monkeypatch: pytest.MonkeyPatch, catalog_of: Callable[..., None], recorded: list[Sequence[str]]
) -> None:
    """Otherwise the first thing a maintainer runs replaces their editable install."""
    catalog_of(_entry("anydoc"))
    _environment(monkeypatch, "editable")

    result = runner.invoke(cli.app, ["plugins", "install", "anydoc"])

    assert result.exit_code == 1
    assert "uv sync --extra anydoc" in result.stderr
    assert recorded == []


def test_plugins_install_without_uv_says_what_to_run(
    monkeypatch: pytest.MonkeyPatch, catalog_of: Callable[..., None], recorded: list[Sequence[str]]
) -> None:
    catalog_of(_entry("anydoc"))
    monkeypatch.setattr(cli, "detect", lambda: Environment("unmanaged", Path("/p"), None))

    result = runner.invoke(cli.app, ["plugins", "install", "anydoc"])

    assert result.exit_code == 1
    assert "moodle-cli[anydoc]" in result.stderr
    assert recorded == []


def test_plugins_install_in_a_plain_venv_targets_that_interpreter(
    monkeypatch: pytest.MonkeyPatch, catalog_of: Callable[..., None], recorded: list[Sequence[str]]
) -> None:
    catalog_of(_entry("anydoc"))
    _environment(monkeypatch, "uv-managed")

    result = runner.invoke(cli.app, ["plugins", "install", "anydoc"])

    assert result.exit_code == 0
    assert list(recorded[0]) == [
        "/usr/bin/uv",
        "pip",
        "install",
        "--python",
        "/env/bin/python",
        "moodle-cli[anydoc]",
    ]


# -- uninstall -----------------------------------------------------------------------


def test_plugins_uninstall_drops_only_the_named_extra(
    monkeypatch: pytest.MonkeyPatch, catalog_of: Callable[..., None], recorded: list[Sequence[str]]
) -> None:
    catalog_of(
        _entry("anydoc", installed=True, version="0.1.0"),
        _entry("panopto", installed=True, version="0.1.0"),
    )
    _environment(monkeypatch, "uv-tool", injected=[])

    result = runner.invoke(cli.app, ["plugins", "uninstall", "panopto"])

    assert result.exit_code == 0
    assert "moodle-cli[anydoc]" in recorded[0]


def test_plugins_uninstall_is_a_no_op_when_it_was_never_installed(
    catalog_of: Callable[..., None], recorded: list[Sequence[str]]
) -> None:
    catalog_of(_entry("anydoc"))

    result = runner.invoke(cli.app, ["plugins", "uninstall", "anydoc"])

    assert result.exit_code == 0
    assert recorded == []


# -- reading uv's answer -------------------------------------------------------------


@pytest.mark.parametrize(
    ("stdout", "expected"),
    [
        ("moodle-cli v0.1.0 [with: a, b]\n- moodle\n", ["a", "b"]),
        ("moodle-cli v0.1.0\n- moodle\n", []),
        ("other-tool v1.0 [with: x]\n- other\n", None),
        ("", None),
    ],
)
def test_the_injected_set_is_read_from_uvs_own_listing(
    monkeypatch: pytest.MonkeyPatch, stdout: str, expected: list[str] | None
) -> None:
    """A tool moodle-cli is not in must read as unknown, not as an empty set."""

    def fake_run(argv: Sequence[str], **kwargs: Any) -> Any:
        return type("Result", (), {"stdout": stdout})()

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert injected_packages("/usr/bin/uv") == expected


@pytest.mark.parametrize(
    ("direct_url", "expected"),
    [
        # Only this one points back at a checkout someone can edit.
        ('{"url": "file:///src/moodle-cli", "dir_info": {"editable": true}}', True),
        # PEP 610 writes direct_url.json for these too, and none of them is a checkout.
        ('{"url": "file:///src/moodle-cli", "dir_info": {"editable": false}}', False),
        ('{"url": "file:///tmp/moodle_cli-0.1.0-py3-none-any.whl", "archive_info": {}}', False),
        ('{"url": "https://github.com/varbelaiz/moodle-cli", "vcs_info": {"vcs": "git"}}', False),
        (None, False),  # a plain wheel from an index has no direct_url.json at all
        ("not json", False),
    ],
)
def test_only_an_editable_install_counts_as_a_checkout(
    monkeypatch: pytest.MonkeyPatch, direct_url: str | None, expected: bool
) -> None:
    """`plugins install` refuses on a checkout, so a false positive refuses everywhere.

    A wheel or a git URL installed with `uv tool install` also carries direct_url.json;
    reading its presence alone would send those users to a `uv sync` in a checkout they
    may not have.
    """
    monkeypatch.setattr(
        toolenv,
        "distribution",
        lambda name: type("Dist", (), {"read_text": lambda self, path: direct_url})(),
    )

    assert toolenv._is_editable() is expected
