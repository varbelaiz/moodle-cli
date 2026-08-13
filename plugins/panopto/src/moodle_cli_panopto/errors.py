"""The one exception type this plugin raises on its own.

Caller-input problems (an ambiguous session, a language the recording does not have)
raise ``ValueError`` instead, matching ``moodle_cli_anydoc``'s ``fetch_and_convert``
convention -- ``cli.py`` catches both alongside ``moodle_cli.errors.MoodleError``.
"""

from __future__ import annotations


class PanoptoError(Exception):
    """Login, session, or transcript retrieval failed."""
