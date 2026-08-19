"""Tests for `moodle version` and `moodle update`.

The GitHub call and the packaging command are faked at the boundary, same as
`test_plugins_cli.py`: what matters here is the argv `update` builds and when it decides
not to build one at all.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest
from typer.testing import CliRunner

from moodle_cli import cli
from moodle_cli.toolenv import Environment

runner = CliRunner()


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
    monkeypatch: pytest.MonkeyPatch, kind: str, *, uv: str | None = "/usr/bin/uv"
) -> None:
    monkeypatch.setattr(
        cli,
        "detect",
        lambda: Environment(kind, Path("/env/bin/python"), uv),  # type: ignore[arg-type]
    )


def _installed(
    monkeypatch: pytest.MonkeyPatch,
    *,
    extras: set[str],
    injected: list[str] | None = None,
) -> None:
    monkeypatch.setattr(cli, "installed_extras", lambda: frozenset(extras))
    monkeypatch.setattr(cli, "extra_distributions", lambda: {e: f"moodle-cli-{e}" for e in extras})
    monkeypatch.setattr(cli, "injected_packages", lambda uv: injected)


def _pinned_version(monkeypatch: pytest.MonkeyPatch, version: str) -> None:
    monkeypatch.setattr(cli, "__version__", version)


# -- version ---------------------------------------------------------------------------


def test_version_never_reaches_the_network_without_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pinned_version(monkeypatch, "0.1.0")

    def fail() -> str:
        raise AssertionError("latest_release() should not be called without --check")

    monkeypatch.setattr(cli, "latest_release", fail)

    result = runner.invoke(cli.app, ["version"])

    assert result.exit_code == 0
    assert "0.1.0" in result.stdout


def test_version_check_reports_up_to_date(monkeypatch: pytest.MonkeyPatch) -> None:
    _pinned_version(monkeypatch, "0.2.0")
    monkeypatch.setattr(cli, "latest_release", lambda: "v0.2.0")

    result = runner.invoke(cli.app, ["version", "--check"])

    assert result.exit_code == 0
    assert "Up to date" in result.stdout


def test_version_check_reports_an_available_update(monkeypatch: pytest.MonkeyPatch) -> None:
    _pinned_version(monkeypatch, "0.1.0")
    monkeypatch.setattr(cli, "latest_release", lambda: "v0.2.0")

    result = runner.invoke(cli.app, ["version", "--check"])

    assert result.exit_code == 0
    assert "v0.2.0" in result.stdout
    assert "moodle update" in result.stdout


def test_version_check_json_reports_update_available(monkeypatch: pytest.MonkeyPatch) -> None:
    _pinned_version(monkeypatch, "0.1.0")
    monkeypatch.setattr(cli, "latest_release", lambda: "v0.2.0")

    result = runner.invoke(cli.app, ["version", "--check", "--json"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {
        "version": "0.1.0",
        "latest": "v0.2.0",
        "update_available": True,
    }


# -- update ------------------------------------------------------------------------------


def test_update_is_a_no_op_when_already_current(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Sequence[str]]
) -> None:
    _pinned_version(monkeypatch, "0.2.0")
    monkeypatch.setattr(cli, "latest_release", lambda: "v0.2.0")

    result = runner.invoke(cli.app, ["update"])

    assert result.exit_code == 0
    assert "Already up to date" in result.stdout
    assert recorded == []


def test_update_json_reports_up_to_date(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Sequence[str]]
) -> None:
    _pinned_version(monkeypatch, "0.2.0")
    monkeypatch.setattr(cli, "latest_release", lambda: "v0.2.0")

    result = runner.invoke(cli.app, ["update", "--json"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {"action": "up-to-date", "version": "0.2.0"}
    assert recorded == []


def test_update_upgrades_a_uv_tool_install(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Sequence[str]]
) -> None:
    _pinned_version(monkeypatch, "0.1.0")
    monkeypatch.setattr(cli, "latest_release", lambda: "v0.2.0")
    _environment(monkeypatch, "uv-tool")
    _installed(monkeypatch, extras={"anydoc"}, injected=[])

    result = runner.invoke(cli.app, ["update"])

    assert result.exit_code == 0, result.stderr
    assert list(recorded[0]) == [
        "/usr/bin/uv",
        "tool",
        "install",
        "--reinstall",
        "moodle-cli[anydoc] @ git+https://github.com/varbelaiz/moodle-cli@v0.2.0",
    ]
    assert "Updated" in result.stdout
    assert "v0.2.0" in result.stdout


def test_update_preserves_packages_injected_by_hand(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Sequence[str]]
) -> None:
    _pinned_version(monkeypatch, "0.1.0")
    monkeypatch.setattr(cli, "latest_release", lambda: "v0.2.0")
    _environment(monkeypatch, "uv-tool")
    _installed(monkeypatch, extras=set(), injected=["some-unrelated-tool==1.2"])

    result = runner.invoke(cli.app, ["update"])

    assert result.exit_code == 0, result.stderr
    assert list(recorded[0]) == [
        "/usr/bin/uv",
        "tool",
        "install",
        "--reinstall",
        "moodle-cli @ git+https://github.com/varbelaiz/moodle-cli@v0.2.0",
        "--with",
        "some-unrelated-tool==1.2",
    ]


def test_update_in_a_plain_venv_targets_that_interpreter(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Sequence[str]]
) -> None:
    _pinned_version(monkeypatch, "0.1.0")
    monkeypatch.setattr(cli, "latest_release", lambda: "v0.2.0")
    _environment(monkeypatch, "uv-managed")
    _installed(monkeypatch, extras=set())

    result = runner.invoke(cli.app, ["update"])

    assert result.exit_code == 0, result.stderr
    assert list(recorded[0]) == [
        "/usr/bin/uv",
        "pip",
        "install",
        "--python",
        "/env/bin/python",
        "moodle-cli @ git+https://github.com/varbelaiz/moodle-cli@v0.2.0",
    ]


def test_update_uv_tool_refuses_when_injected_packages_cannot_be_read(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Sequence[str]]
) -> None:
    """Reinstalling without restating an unreadable `--with` set would drop it in silence."""
    _pinned_version(monkeypatch, "0.1.0")
    monkeypatch.setattr(cli, "latest_release", lambda: "v0.2.0")
    _environment(monkeypatch, "uv-tool")
    _installed(monkeypatch, extras={"anydoc"}, injected=None)

    result = runner.invoke(cli.app, ["update"])

    assert result.exit_code == 1
    assert "uv tool install --reinstall" in result.stderr
    assert recorded == []


def test_update_rejects_an_editable_install(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Sequence[str]]
) -> None:
    _pinned_version(monkeypatch, "0.1.0")
    monkeypatch.setattr(cli, "latest_release", lambda: "v0.2.0")
    _environment(monkeypatch, "editable")

    result = runner.invoke(cli.app, ["update"])

    assert result.exit_code == 1
    assert "editable install" in result.stderr
    assert recorded == []


def test_update_without_uv_tells_the_user_the_command_to_run(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Sequence[str]]
) -> None:
    _pinned_version(monkeypatch, "0.1.0")
    monkeypatch.setattr(cli, "latest_release", lambda: "v0.2.0")
    _environment(monkeypatch, "unmanaged", uv=None)
    _installed(monkeypatch, extras={"anydoc"})

    result = runner.invoke(cli.app, ["update"])

    assert result.exit_code == 1
    expected_spec = "moodle-cli[anydoc] @ git+https://github.com/varbelaiz/moodle-cli@v0.2.0"
    assert expected_spec in result.stderr
    assert recorded == []


def test_update_json_reports_what_it_did(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Sequence[str]]
) -> None:
    _pinned_version(monkeypatch, "0.1.0")
    monkeypatch.setattr(cli, "latest_release", lambda: "v0.2.0")
    _environment(monkeypatch, "uv-tool")
    _installed(monkeypatch, extras=set(), injected=[])

    result = runner.invoke(cli.app, ["update", "--json"])

    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["action"] == "updated"
    assert payload["from"] == "0.1.0"
    assert payload["to"] == "v0.2.0"
    assert payload["environment"] == "uv-tool"
