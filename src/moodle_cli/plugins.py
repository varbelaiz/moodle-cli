"""Discovery and mounting of optional plugins.

Plugins are additive. They contribute a command group and MCP tools; they cannot wrap,
replace or modify anything the core exposes. That restriction is the point: a package that
could wrap `course download` would make this tool's behaviour unauditable from its own
source.

The host does the mounting and the naming, not the plugin, so two plugins cannot collide
and neither can shadow a core command. Every failure here is a skip with a recorded reason:
`moodle --help` answering on a machine with a bad plugin installed is not negotiable.
"""

from __future__ import annotations

import logging
import os
import re
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import cache
from importlib.metadata import PackageNotFoundError, distribution, entry_points, metadata
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # Neither surface should pay for the other's imports.
    import typer
    from mcp.server.fastmcp import FastMCP

log = logging.getLogger(__name__)

API_VERSION = 1
ENTRY_POINT_GROUP = "moodle_cli.plugins"
DISABLE_ENV = "MOODLE_NO_PLUGINS"
CORE_DISTRIBUTION = "moodle-cli"

# Command groups the core owns. A plugin mounted over one of these would shadow it, and a
# shadowed `auth login` is a password prompt from somewhere the user did not expect.
RESERVED_NAMES = frozenset({"auth", "course", "courses", "plugins"})

# An extra that installs several plugins at once names no plugin of its own.
AGGREGATE_EXTRAS = frozenset({"all"})

_PLUGIN_NAME = re.compile(r"^[a-z][a-z0-9-]*$")
_EXTRA_MARKER = re.compile(r"""extra\s*==\s*['"]([A-Za-z0-9._-]+)['"]""")
_REQUIREMENT_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


class Plugin:
    """Base class for a moodle-cli plugin.

    Subclass it, set ``name``, and override whichever contribution applies; both are
    optional. Import typer and your tool functions *inside* the methods rather than at
    module scope, so the MCP server never pays for typer and the CLI never pays for mcp.
    """

    #: The command group this mounts under, and the prefix its MCP tools carry.
    name: str = ""

    #: The host contract this plugin was written against. A mismatch is skipped.
    api_version: int = API_VERSION

    def commands(self) -> typer.Typer | None:
        """A Typer app to mount as ``moodle <name>``. Give it a ``help`` string."""
        return None

    def tools(self) -> Sequence[Callable[..., Any]]:
        """Functions to expose as MCP tools, named ``<name>_<function name>``."""
        return ()


@dataclass(frozen=True)
class LoadedPlugin:
    """A plugin that was found, instantiated and accepted."""

    name: str
    distribution: str
    plugin: Plugin


@dataclass(frozen=True)
class SkippedPlugin:
    """A plugin that was found and rejected, and why, so `plugins list` can say so."""

    distribution: str
    reason: str


@dataclass(frozen=True)
class Discovery:
    loaded: tuple[LoadedPlugin, ...]
    skipped: tuple[SkippedPlugin, ...]


@cache
def _discover() -> Discovery:
    """Scan, instantiate and validate every installed plugin, exactly once.

    Cached because scanning entry points walks every distribution on the path, and both
    surfaces plus `plugins list` ask for the same answer within one process.
    """
    if os.environ.get(DISABLE_ENV):
        return Discovery((), ())

    loaded: list[LoadedPlugin] = []
    skipped: list[SkippedPlugin] = []
    taken: set[str] = set()

    for entry in sorted(entry_points(group=ENTRY_POINT_GROUP), key=lambda e: e.name):
        dist = getattr(getattr(entry, "dist", None), "name", None) or entry.name
        try:
            loaded_object = entry.load()
            candidate = loaded_object() if isinstance(loaded_object, type) else loaded_object
        # Bare Exception on purpose: this imports third-party code, which can raise anything.
        except Exception as exc:
            log.warning("Skipping plugin %r: it failed to load (%s).", dist, exc)
            skipped.append(SkippedPlugin(dist, f"failed to load: {exc}"))
            continue

        problem: str | None
        if not isinstance(candidate, Plugin):
            problem = f"{type(candidate).__name__} is not a moodle_cli.Plugin"
        else:
            problem = _reject(candidate, taken)
        if problem is not None:
            log.warning("Skipping plugin %r: %s.", dist, problem)
            skipped.append(SkippedPlugin(dist, problem))
            continue

        taken.add(candidate.name)
        loaded.append(LoadedPlugin(name=candidate.name, distribution=dist, plugin=candidate))

    return Discovery(tuple(loaded), tuple(skipped))


def _reject(candidate: Plugin, taken: set[str]) -> str | None:
    """Why this plugin cannot be mounted, or None if it can."""
    if candidate.api_version != API_VERSION:
        # Equality rather than a floor: a plugin written against a contract this host has
        # never seen is not something to guess at.
        return f"it targets plugin API v{candidate.api_version}, this host speaks v{API_VERSION}"
    if not _PLUGIN_NAME.match(candidate.name):
        return f"{candidate.name!r} is not a usable command name"
    if candidate.name in RESERVED_NAMES:
        return f"{candidate.name!r} is a core command group"
    if candidate.name in taken:
        return f"another plugin is already mounted at {candidate.name!r}"
    return None


def load_plugins() -> tuple[LoadedPlugin, ...]:
    """Every plugin that is installed and usable."""
    return _discover().loaded


def skipped_plugins() -> tuple[SkippedPlugin, ...]:
    """Every plugin that is installed and was rejected, with the reason."""
    return _discover().skipped


def reset() -> None:
    """Forget the discovery and catalog caches. For tests, and only for tests."""
    _discover.cache_clear()
    catalog.cache_clear()


# -- mounting ----------------------------------------------------------------------


def mount_commands(app: typer.Typer) -> None:
    """Add each plugin's command group under its own name."""
    for entry in load_plugins():
        try:
            group = entry.plugin.commands()
        except Exception as exc:
            log.warning("Plugin %r failed to build its commands (%s).", entry.name, exc)
            continue
        if group is not None:
            app.add_typer(group, name=entry.name)


def register_tools(mcp: FastMCP) -> None:
    """Register each plugin's tools, prefixed with the plugin's name.

    Prefixing is the host's job so a plugin cannot pick a name that collides with a core
    tool, and so an agent reading the tool list can tell where a tool came from. Core tools
    are registered first and FastMCP keeps the first registration of a name, so even a
    colliding prefix cannot displace one.
    """
    for entry in load_plugins():
        try:
            functions = entry.plugin.tools()
        except Exception as exc:
            log.warning("Plugin %r failed to build its tools (%s).", entry.name, exc)
            continue
        for function in functions:
            function_name = getattr(function, "__name__", "")
            if not function_name:
                log.warning("Plugin %r offered an unnamed tool; skipping it.", entry.name)
                continue
            try:
                # One at a time: an unannotated signature raises here, and one bad tool
                # must not cost the plugin the rest of them.
                mcp.add_tool(function, name=f"{entry.name}_{function_name}")
            except Exception as exc:
                log.warning(
                    "Plugin %r: tool %r could not be registered (%s).",
                    entry.name,
                    function_name,
                    exc,
                )


def tool_names(entry: LoadedPlugin) -> tuple[str, ...]:
    """The MCP tool names a plugin contributes, for `moodle plugins list`."""
    try:
        return tuple(f"{entry.name}_{f.__name__}" for f in entry.plugin.tools())
    except Exception:
        return ()


# -- catalog -----------------------------------------------------------------------


@dataclass(frozen=True)
class CatalogEntry:
    """A plugin, and what is known about it in this environment."""

    name: str  # what `plugins list` shows; for an official plugin, also its extra
    distribution: str
    official: bool  # declared as an extra of the core, so installable from this CLI
    installed: bool
    version: str | None
    summary: str | None  # only readable once installed; it lives in the plugin's metadata
    mounted_as: str | None  # the command group, knowable only once imported
    tools: tuple[str, ...]
    problem: str | None  # installed but rejected, and why


def extra_distributions() -> dict[str, str]:
    """Map each plugin extra to the distribution it installs, from the core's metadata.

    The extras already are the list of plugins a release knows about, so reading them back
    is what keeps this from being a second copy of that list with its own drift. It reads
    the *installed* metadata, so an edit to pyproject.toml only shows up after a re-sync.
    """
    try:
        requirements = metadata(CORE_DISTRIBUTION).get_all("Requires-Dist") or []
    except PackageNotFoundError:
        return {}

    grouped: dict[str, list[str]] = defaultdict(list)
    for requirement in requirements:
        head, _, marker = str(requirement).partition(";")
        extra = _EXTRA_MARKER.search(marker)
        name = _REQUIREMENT_NAME.match(head)
        if extra and name:
            grouped[extra.group(1)].append(name.group(1))

    # An extra naming exactly one distribution is a plugin; anything else is an umbrella.
    return {
        extra: names[0]
        for extra, names in grouped.items()
        if len(names) == 1 and extra not in AGGREGATE_EXTRAS
    }


@cache
def catalog() -> tuple[CatalogEntry, ...]:
    """Every official plugin, plus any third-party one installed here.

    Third-party plugins are listed even though this CLI cannot install them, because a
    command group appearing in `--help` from nowhere, or a plugin skipped for a reason
    nobody can see, is exactly what this command exists to explain.
    """
    by_distribution = {entry.distribution: entry for entry in load_plugins()}
    problems = {entry.distribution: entry.reason for entry in skipped_plugins()}
    official = extra_distributions()

    entries: list[CatalogEntry] = []
    for extra, dist_name in sorted(official.items()):
        version, summary = _installed(dist_name)
        mounted = by_distribution.get(dist_name)
        entries.append(
            CatalogEntry(
                name=extra,
                distribution=dist_name,
                official=True,
                installed=version is not None,
                version=version,
                summary=summary,
                mounted_as=mounted.name if mounted else None,
                tools=tool_names(mounted) if mounted else (),
                problem=problems.get(dist_name),
            )
        )

    catalogued = set(official.values())
    for dist_name in sorted(set(by_distribution) | set(problems)):
        if dist_name in catalogued:
            continue
        version, summary = _installed(dist_name)
        mounted = by_distribution.get(dist_name)
        entries.append(
            CatalogEntry(
                name=mounted.name if mounted else dist_name,
                distribution=dist_name,
                official=False,
                installed=True,
                version=version,
                summary=summary,
                mounted_as=mounted.name if mounted else None,
                tools=tool_names(mounted) if mounted else (),
                problem=problems.get(dist_name),
            )
        )
    return tuple(entries)


def _installed(name: str) -> tuple[str | None, str | None]:
    try:
        dist = distribution(name)
    except PackageNotFoundError:
        return None, None
    return dist.version, dist.metadata["Summary"]


def installed_extras() -> frozenset[str]:
    """The official plugin extras currently satisfied in this environment.

    Third-party plugins are excluded: they are not extras, so restating them as one would
    ask the resolver for something the core does not declare.
    """
    return frozenset(entry.name for entry in catalog() if entry.official and entry.installed)
