"""Signing in to Panopto through the campus, the way a browser's first visit does.

Panopto trusts the campus as an identity provider, under the instance name the block's
recording links carry. Its login page, asked for that instance with ``AllowBounce``,
redirects to the campus's Panopto block SSO endpoint, which vouches for whoever holds
the Moodle session cookie, and back to Panopto with a signed auth code. The session this
ends in belongs to the user, not to a course, so it reaches every recording the user can
see, whether or not the course also has a Panopto activity.
"""

from __future__ import annotations

import httpx

from moodle_cli_panopto.errors import PanoptoError, wrap_http_errors
from moodle_cli_panopto.moodle_login import MoodleWebSession
from moodle_cli_panopto.recordings import Recording

_LOGIN_PATH = "/Panopto/Pages/Auth/Login.aspx"
_AUTH_COOKIE = ".ASPXAUTH"


def open_panopto_session(moodle: MoodleWebSession, recording: Recording) -> httpx.Client:
    """A client signed in to RECORDING's Panopto host as the Moodle session's user.

    Success is decided by Panopto's auth cookie, never by the status code: a rejected
    sign-in ends on a login page that answers 200.
    """
    if recording.instance is None:
        raise PanoptoError(
            f"{recording.host}: the recording link names no Panopto instance to sign in with"
        )
    panopto = httpx.Client(
        base_url=f"https://{recording.host}",
        cookies=moodle.client.cookies,
        timeout=30,
        follow_redirects=True,
    )
    try:
        with wrap_http_errors(f"{recording.host}: signing in through the campus failed"):
            response = panopto.get(
                _LOGIN_PATH, params={"instance": recording.instance, "AllowBounce": "true"}
            )
            response.raise_for_status()
        if not any(cookie.name == _AUTH_COOKIE for cookie in panopto.cookies.jar):
            raise PanoptoError(
                f"{recording.host}: Panopto did not accept the campus sign-in "
                f"for instance {recording.instance!r}"
            )
    except BaseException:
        panopto.close()
        raise
    return panopto


__all__ = ["open_panopto_session"]
