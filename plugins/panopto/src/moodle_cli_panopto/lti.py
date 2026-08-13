"""Establishing a Panopto session via the course's Panopto LTI activity.

A course can carry more than one "External tool" activity (Zoom alongside Panopto is
common here), so the Panopto one has to be found among them. The launch form Moodle
serves for each is already OAuth1-signed server-side -- this plugin never computes or
needs the shared secret, only relays the hidden fields verbatim to whatever host the
form's own ``action`` names, and that host is exactly how the right one is identified,
checkable from a bare GET before anything is posted.
"""

from __future__ import annotations

from html.parser import HTMLParser

import httpx

from moodle_cli.client import MoodleClient
from moodle_cli_panopto.errors import PanoptoError
from moodle_cli_panopto.moodle_login import MoodleWebSession

_LAUNCH_PATH = "/mod/lti/launch.php"
_PANOPTO_HOST_SUFFIX = ".hosted.panopto.com"

#: (base_url, course_id) -> the lti cmid that resolved to Panopto last time, so a
#: repeat call in the same process does not re-probe every external tool in the course.
_cmid_cache: dict[tuple[str, int], int] = {}


class _LtiFormParser(HTMLParser):
    """Extracts a launch form's ``action`` and its hidden ``<input>`` fields.

    A real parser rather than a regex: the whole OAuth1 signature depends on relaying
    these fields exactly, and attribute order (``type``/``name``/``value``) is not
    something a regex can safely assume.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.action: str | None = None
        self.fields: dict[str, str] = {}
        self._in_form = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "form" and self.action is None:
            self.action = attributes.get("action")
            self._in_form = True
        elif tag == "input" and self._in_form and attributes.get("type") == "hidden":
            name = attributes.get("name")
            if name is not None:
                self.fields[name] = attributes.get("value") or ""


def _parse_launch_form(markup: str) -> tuple[str, dict[str, str]] | None:
    parser = _LtiFormParser()
    parser.feed(markup)
    return (parser.action, parser.fields) if parser.action is not None else None


def _candidate_cmids(ws_client: MoodleClient, course_id: int) -> list[int]:
    sections = ws_client.get_course_contents(course_id)
    return [
        module.id for section in sections for module in section.modules if module.modname == "lti"
    ]


def _try_launch(moodle: MoodleWebSession, cmid: int) -> tuple[httpx.Client, str] | None:
    """GET the launch form for CMID and, if its action targets a Panopto host, relay it.

    Returns None -- without ever POSTing -- for any other external tool, so probing a
    course's non-Panopto activities (a Zoom link, say) has no side effects on them.
    """
    response = moodle.client.get(_LAUNCH_PATH, params={"id": cmid})
    response.raise_for_status()
    parsed = _parse_launch_form(response.text)
    if parsed is None:
        return None
    action, fields = parsed

    host = httpx.URL(action).host
    if not host or not host.endswith(_PANOPTO_HOST_SUFFIX):
        return None

    panopto = httpx.Client(base_url=f"https://{host}", timeout=30, follow_redirects=True)
    try:
        panopto.post(action, data=fields)
    except BaseException:
        panopto.close()
        raise
    return panopto, host


def establish_panopto_session(
    moodle: MoodleWebSession, ws_client: MoodleClient, base_url: str, course_id: int
) -> tuple[httpx.Client, str]:
    """Return ``(panopto_client, panopto_host)`` for COURSE_ID.

    Tries the cmid cached from a previous call first; on a miss, probes every ``lti``
    activity in the course until the Panopto one is found, then caches it. Raises
    PanoptoError if none of the course's external tools is Panopto.
    """
    key = (base_url, course_id)
    candidates = _candidate_cmids(ws_client, course_id)

    cached = _cmid_cache.get(key)
    ordered = (
        [cached, *(c for c in candidates if c != cached)] if cached is not None else candidates
    )

    for cmid in ordered:
        if cmid is None:
            continue
        result = _try_launch(moodle, cmid)
        if result is not None:
            _cmid_cache[key] = cmid
            return result

    raise PanoptoError(f"course {course_id}: no Panopto activity found among its external tools")


def reset_cache() -> None:
    """Forget every cached cmid. For tests, and only for tests."""
    _cmid_cache.clear()


__all__ = ["establish_panopto_session", "reset_cache"]
