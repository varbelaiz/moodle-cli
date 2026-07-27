"""CLI and MCP server for a Moodle campus."""

from moodle_cli.errors import AuthError, DownloadError, MoodleAPIError, MoodleError

__all__ = ["AuthError", "DownloadError", "MoodleAPIError", "MoodleError"]
__version__ = "0.1.0"
