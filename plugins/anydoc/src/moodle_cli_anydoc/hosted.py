"""Converting a file via Firecrawl Parse: the hosted, OCR-capable alternative to the
local `anydoc` converter, used only when a caller opts in.

Firecrawl's own SDK imports are kept at module level rather than lazily inside a
function -- unlike `convert.py`'s `anydoc` import -- so a test can monkeypatch
`Firecrawl` here directly instead of hitting the network or a paid API.
"""

from __future__ import annotations

import os
from pathlib import Path

from firecrawl import Firecrawl
from firecrawl.v2.types import ParseOptions, PDFParser

from moodle_cli.config import ensure_env_loaded


class HostedError(Exception):
    """A Firecrawl Parse call failed."""


def resolve_firecrawl_key() -> str | None:
    """FIRECRAWL_KEY from the environment or .env, or None if unset."""
    ensure_env_loaded()
    return os.environ.get("FIRECRAWL_KEY")


def convert_hosted(source: Path, api_key: str) -> str:
    """Convert SOURCE to markdown via Firecrawl Parse, forcing OCR on every PDF page.

    The SDK's `parsers` option only has a PDF-specific config (`PDFParser`) -- there is
    no equivalent for other formats, so this forces OCR for a PDF but has no effect on
    a non-PDF upload (.pptx, .docx, ...), which gets whatever handling Firecrawl applies
    by default for that format.

    Firecrawl's SDK has no single exception type for a failed call: a rejected HTTP
    response raises the SDK's own FirecrawlError, an API response shaped
    {"success": false} raises a bare Exception, and a network failure raises requests'
    own exception hierarchy (the SDK uses requests, not this project's usual httpx).
    Catching Exception broadly is deliberate, not a shortcut -- there is no narrower
    type that covers all three.
    """
    # 300s matches Firecrawl's own documented maximum for a /parse call; unset, the SDK
    # forwards timeout=None straight into requests, which waits forever on a stalled call.
    client = Firecrawl(api_key=api_key, timeout=300)
    options = ParseOptions(parsers=[PDFParser(mode="ocr")])
    try:
        document = client.parse(source, options=options)
    except Exception as exc:
        raise HostedError(str(exc)) from exc

    # firecrawl ships no type information, so mypy sees `document` as Any; this
    # annotation is what pins its `.markdown` field back to the SDK's own declared type.
    markdown: str | None = document.markdown
    if not markdown:
        raise HostedError("Firecrawl Parse returned no markdown for this file")
    return markdown
