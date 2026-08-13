"""The one exception type this plugin raises on its own.

Caller-input problems (an ambiguous session, a language the recording does not have)
raise ``ValueError`` instead, matching ``moodle_cli_anydoc``'s ``fetch_and_convert``
convention -- ``cli.py`` catches both alongside ``moodle_cli.errors.MoodleError``.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import httpx


class PanoptoError(Exception):
    """Login, session, or transcript retrieval failed."""


@contextmanager
def wrap_http_errors(context: str) -> Iterator[None]:
    """Turn any httpx failure -- a non-2xx status, a timeout, a connection error --
    into a PanoptoError.

    Every network call this plugin makes goes through here, so a caller (``cli.py``'s
    error handler, ``fetch.py``'s per-recording batch catch) only ever needs to catch
    PanoptoError for anything this plugin's own HTTP calls can raise, never httpx
    itself -- the same discipline ``moodle_cli.client.check_api_error`` gives the core
    web-service surface, extended to cover transport failures the core doesn't have to
    worry about (its calls stay on one host; this plugin's cross two).
    """
    try:
        yield
    except httpx.HTTPError as exc:
        raise PanoptoError(f"{context}: {exc}") from exc
