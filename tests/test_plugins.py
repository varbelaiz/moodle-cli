"""Tests for plugin discovery, rejection and mounting.

The rule under test throughout: a plugin can add, and nothing a plugin does can take the
core down with it.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest
import typer
from mcp.server.fastmcp import FastMCP
from typer.testing import CliRunner

from moodle_cli import plugins
from moodle_cli.plugins import Plugin

runner = CliRunner()


@dataclass(frozen=True)
class FakeEntryPoint:
    """Stands in for an installed plugin's entry point.

    Discovery is faked at ``moodle_cli.plugins.entry_points`` rather than by installing a
    real package, because what is under test is what the host does with what it finds,
    including what it does with something that refuses to load.
    """

    name: str
    value: Any
    dist_name: str = "fake-plugin"

    @property
    def dist(self) -> SimpleNamespace:
        return SimpleNamespace(name=self.dist_name)

    def load(self) -> Any:
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


@pytest.fixture
def fake_plugins(monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    """Install fake plugins, opting this test out of the autouse isolation."""

    def install(*entries: FakeEntryPoint) -> None:
        monkeypatch.delenv(plugins.DISABLE_ENV, raising=False)
        monkeypatch.setattr(plugins, "entry_points", lambda group: list(entries))
        plugins.reset()

    return install


def greet(name: str) -> str:
    """Say hello."""
    return f"hello {name}"


def unresolvable(value: Forgotten) -> str:  # type: ignore[name-defined] # noqa: F821
    """A tool FastMCP cannot build a schema for, as when an author forgets an import."""
    return str(value)


@dataclass
class Recorder(Plugin):
    """A plugin whose contributions the test dictates."""

    name: str = "demo"
    api_version: int = plugins.API_VERSION
    group: typer.Typer | None = None
    functions: Sequence[Callable[..., Any]] = field(default_factory=tuple)

    def commands(self) -> typer.Typer | None:
        return self.group

    def tools(self) -> Sequence[Callable[..., Any]]:
        return self.functions


def _group(name: str) -> typer.Typer:
    group = typer.Typer(help=f"{name} commands.", no_args_is_help=True)

    @group.command("ping")
    def ping() -> None:
        typer.echo(f"{name} pong")

    return group


def _host() -> typer.Typer:
    """A host app with a command of its own, so `--help` has a group to render."""
    app = typer.Typer(no_args_is_help=True)

    @app.command("core")
    def core() -> None:
        typer.echo("core")

    return app


# -- rejection -----------------------------------------------------------------------


def test_a_plugin_that_fails_to_import_leaves_the_cli_working(
    fake_plugins: Callable[..., None],
) -> None:
    """A broken third-party package must not be able to take `moodle --help` down."""
    fake_plugins(FakeEntryPoint("broken", ImportError("no such module"), "moodle-cli-broken"))

    from moodle_cli.cli import app

    plugins.mount_commands(app)
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "courses" in result.stdout
    assert [s.reason for s in plugins.skipped_plugins()] == ["failed to load: no such module"]


def test_a_plugin_targeting_another_api_version_is_skipped(
    fake_plugins: Callable[..., None],
) -> None:
    """Equality, not a floor: a contract this host never saw is not one to guess at."""
    fake_plugins(FakeEntryPoint("demo", Recorder(api_version=plugins.API_VERSION + 1)))

    assert plugins.load_plugins() == ()
    assert "this host speaks v1" in plugins.skipped_plugins()[0].reason


def test_a_plugin_cannot_mount_over_a_core_command_group(
    fake_plugins: Callable[..., None],
) -> None:
    """A shadowed `auth login` would be a password prompt from an unexpected place."""
    fake_plugins(FakeEntryPoint("evil", Recorder(name="auth", group=_group("auth"))))

    assert plugins.load_plugins() == ()
    assert "core command group" in plugins.skipped_plugins()[0].reason


def test_the_second_plugin_claiming_a_name_is_skipped(
    fake_plugins: Callable[..., None],
) -> None:
    fake_plugins(
        FakeEntryPoint("a", Recorder(name="demo"), "plugin-a"),
        FakeEntryPoint("b", Recorder(name="demo"), "plugin-b"),
    )

    assert [entry.distribution for entry in plugins.load_plugins()] == ["plugin-a"]
    assert "already mounted" in plugins.skipped_plugins()[0].reason


@pytest.mark.parametrize("name", ["", "Demo", "9lives", "with space", "sub.group"])
def test_a_plugin_with_an_unusable_command_name_is_skipped(
    fake_plugins: Callable[..., None], name: str
) -> None:
    fake_plugins(FakeEntryPoint("demo", Recorder(name=name)))

    assert plugins.load_plugins() == ()
    assert "not a usable command name" in plugins.skipped_plugins()[0].reason


def test_something_that_is_not_a_plugin_is_skipped(fake_plugins: Callable[..., None]) -> None:
    fake_plugins(FakeEntryPoint("demo", object()))

    assert plugins.load_plugins() == ()
    assert "not a moodle_cli.Plugin" in plugins.skipped_plugins()[0].reason


# -- mounting ------------------------------------------------------------------------


def test_a_plugins_commands_mount_under_its_own_name(fake_plugins: Callable[..., None]) -> None:
    fake_plugins(FakeEntryPoint("demo", Recorder(group=_group("demo"))))

    app = _host()
    plugins.mount_commands(app)

    assert runner.invoke(app, ["demo", "ping"]).stdout.strip() == "demo pong"


def test_a_plugin_that_raises_while_building_its_commands_is_skipped(
    fake_plugins: Callable[..., None],
) -> None:
    class Exploding(Plugin):
        name = "boom"

        def commands(self) -> typer.Typer:
            raise RuntimeError("no group for you")

    fake_plugins(FakeEntryPoint("boom", Exploding()))

    app = _host()
    plugins.mount_commands(app)

    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "boom" not in result.stdout


def test_a_plugins_tools_are_registered_under_its_own_prefix(
    fake_plugins: Callable[..., None],
) -> None:
    """The host prefixes, so a plugin cannot name a tool into a collision with the core."""
    fake_plugins(FakeEntryPoint("demo", Recorder(functions=(greet,))))

    mcp = FastMCP("test")
    plugins.register_tools(mcp)

    assert [tool.name for tool in mcp._tool_manager.list_tools()] == ["demo_greet"]


def test_one_unregisterable_tool_does_not_cost_a_plugin_the_rest(
    fake_plugins: Callable[..., None],
) -> None:
    """Registering one at a time is what keeps a bad signature from taking the good ones."""
    fake_plugins(FakeEntryPoint("demo", Recorder(functions=(unresolvable, greet))))

    mcp = FastMCP("test")
    plugins.register_tools(mcp)

    assert [tool.name for tool in mcp._tool_manager.list_tools()] == ["demo_greet"]


def test_a_plugin_cannot_displace_a_core_tool(fake_plugins: Callable[..., None]) -> None:
    """FastMCP keeps the first registration, and core tools are registered first."""
    fake_plugins(FakeEntryPoint("demo", Recorder(functions=(greet,))))

    mcp = FastMCP("test")

    @mcp.tool(name="demo_greet")
    def core_greet(name: str) -> str:
        """The core's own."""
        return "core"

    plugins.register_tools(mcp)

    tool = mcp._tool_manager.get_tool("demo_greet")
    assert tool is not None
    assert tool.fn is core_greet


# -- the escape hatch ----------------------------------------------------------------


def test_moodle_no_plugins_disables_discovery_entirely(
    monkeypatch: pytest.MonkeyPatch, fake_plugins: Callable[..., None]
) -> None:
    """The documented way out when a plugin breaks the command line itself."""
    fake_plugins(FakeEntryPoint("demo", Recorder(group=_group("demo"))))
    monkeypatch.setenv(plugins.DISABLE_ENV, "1")
    plugins.reset()

    assert plugins.load_plugins() == ()
    assert plugins.skipped_plugins() == ()


# -- catalog -------------------------------------------------------------------------


def test_an_umbrella_extra_is_not_read_as_a_plugin(monkeypatch: pytest.MonkeyPatch) -> None:
    """`all` installs the others, so it names no plugin of its own and must not list."""
    requirements = [
        "httpx>=0.27",
        'moodle-cli-anydoc; extra == "anydoc"',
        'moodle-cli-anydoc; extra == "all"',
        'moodle-cli-panopto; extra == "all"',
    ]
    monkeypatch.setattr(
        plugins,
        "metadata",
        lambda name: SimpleNamespace(get_all=lambda key: requirements),
    )

    assert plugins.extra_distributions() == {"anydoc": "moodle-cli-anydoc"}


def test_the_catalog_is_empty_when_the_core_declares_no_plugin_extras() -> None:
    """The state this release ships in: the machinery works with nothing to operate on."""
    plugins.reset()

    assert plugins.catalog() == ()
    assert plugins.installed_extras() == frozenset()
