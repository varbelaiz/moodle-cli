"""Exceptions.

The campus signals nearly every failure with HTTP 200 and an error payload in the body,
so these are raised from body inspection rather than from status codes.
"""

from __future__ import annotations


class MoodleError(Exception):
    """Base class for every error this package raises."""


class MoodleAPIError(MoodleError):
    """A web-service call returned an error payload."""

    def __init__(self, errorcode: str, message: str, *, function: str | None = None) -> None:
        self.errorcode = errorcode
        self.message = message
        self.function = function
        where = f" in {function}" if function else ""
        super().__init__(f"{message} [{errorcode}]{where}")


class AuthError(MoodleError):
    """Could not obtain or resolve a token."""


class DownloadError(MoodleError):
    """A file download completed but the result is not the expected file."""
