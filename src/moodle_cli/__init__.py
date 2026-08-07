"""CLI and MCP server for a Moodle campus."""

from moodle_cli.errors import AuthError, DownloadError, MoodleAPIError, MoodleError
from moodle_cli.plugins import API_VERSION, Plugin
from moodle_cli.session import open_client

__all__ = [
    "API_VERSION",
    "AuthError",
    "DownloadError",
    "MoodleAPIError",
    "MoodleError",
    "Plugin",
    "open_client",
]
__version__ = "0.1.0"
