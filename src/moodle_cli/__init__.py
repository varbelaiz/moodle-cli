"""CLI and MCP server for a Moodle campus."""

import importlib.metadata

from moodle_cli.errors import AuthError, DownloadError, MoodleAPIError, MoodleError
from moodle_cli.plugins import API_VERSION, CORE_DISTRIBUTION, Plugin
from moodle_cli.session import open_client

try:
    from moodle_cli._version import __version__ as __version__
except ModuleNotFoundError:
    # Generated at build/sync time and gitignored, so it is absent if something (e.g.
    # `git clean -fdx`) removes it without triggering a rebuild. The installed
    # distribution's own recorded version is the next best source of truth.
    __version__ = importlib.metadata.version(CORE_DISTRIBUTION)

__all__ = [
    "API_VERSION",
    "AuthError",
    "DownloadError",
    "MoodleAPIError",
    "MoodleError",
    "Plugin",
    "__version__",
    "open_client",
]
