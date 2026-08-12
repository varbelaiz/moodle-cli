"""Getting from configuration to a usable client.

One function, because the surfaces that need a client differ only in whether they may mint
a token, and the client already carries everything else they used to reach around it for.
"""

from __future__ import annotations

from moodle_cli.auth import resolve_token
from moodle_cli.client import MoodleClient
from moodle_cli.config import load_config


def open_client(*, allow_mint: bool = True) -> MoodleClient:
    """Build a client for the configured campus, with a resolved token.

    Returns the client rather than a context manager wrapping one: ``MoodleClient`` is
    already a context manager, so ``with open_client() as client:`` reads the same and
    there is no second object to keep in step with it. The raw token, needed to fetch a
    file from ``pluginfile.php``, is on ``client.token``, which is why this hands back a
    client and not a pair.

    ``allow_mint=False`` is for reporting on a session that should already exist: it makes
    a missing token an error instead of a password prompt.
    """
    config = load_config()
    return MoodleClient(config.base_url, resolve_token(config, allow_mint=allow_mint))
