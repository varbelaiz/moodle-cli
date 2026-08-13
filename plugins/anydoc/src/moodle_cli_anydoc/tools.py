"""The MCP-facing conversion tools, registered as `anydoc_convert_to_markdown` and
`anydoc_get_markdown`.

Split by what each is for, not just by input shape. `convert_to_markdown` transforms
files already on disk -- a batch, for storing alongside course material or in a vault --
and returns paths only, on purpose: the caller already has (or is about to have) these
files, and the whole point is persistence, not reading. `get_markdown` is the read-one-
document case: it reaches the campus itself, so the point of one call is not making the
agent chain a fetch and a read together for something as small as a course handout.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from moodle_cli_anydoc.convert import ConversionError, convert_file
from moodle_cli_anydoc.fetch import fetch_and_convert

INLINE_LIMIT = 20_000


def convert_to_markdown(paths: list[str], *, ocr: bool = False) -> list[dict[str, Any]]:
    """Convert one or more files already on disk to markdown.

    Writes `<path>.md` alongside each file and returns a path-only manifest -- no
    content, since this is meant for a batch (e.g. building a vault) rather than for
    reading any one of them. One file failing does not stop the rest.

    `ocr=True` converts via Firecrawl Parse (hosted, OCR) instead of locally -- useful
    for scanned pages or image-heavy slides the local converter reads as blank. It
    requires `FIRECRAWL_KEY` and sends each file to a third-party API, so use it only
    when a document is known to need it, not as a default.
    """
    results: list[dict[str, Any]] = []
    for raw in paths:
        try:
            converted = convert_file(Path(raw), ocr=ocr)
        except ConversionError as exc:
            results.append({"path": raw, "status": "error", "error": str(exc)})
            continue
        results.append(
            {
                "path": str(converted.source),
                "markdown_path": str(converted.markdown_path),
                "status": "converted",
            }
        )
    return results


def get_markdown(
    course: str, filename: str, section: int | None = None, *, ocr: bool = False
) -> dict[str, Any]:
    """Fetch one course file and convert it to markdown, in a single call.

    `course` accepts a numeric id or a shortname prefix; `filename` is the exact name
    from get_course_contents. `section` disambiguates the rare case where a duplicated
    activity produces two same-named files of different sizes in one course.

    `ocr=True` converts via Firecrawl Parse (hosted, OCR) instead of locally -- useful
    when the local conversion of this same file came back with little or no body text
    (scanned pages, image-heavy slides). Requires `FIRECRAWL_KEY` and sends the file to
    a third-party API, so only set it once the local result is known to be lacking.

    Writes the result to `<path>.md` and always returns that full path; `markdown` is
    capped at 20,000 characters, with `truncated` true when the file's own contents run
    longer -- read the rest from `markdown_path` directly.

    Raises if `course` or `filename` do not resolve, or if the file cannot be converted
    -- encrypted, corrupt, or an unsupported format.
    """
    converted = fetch_and_convert(course, filename, section=section, ocr=ocr)
    markdown = converted.markdown
    truncated = len(markdown) > INLINE_LIMIT
    return {
        "path": str(converted.source),
        "markdown_path": str(converted.markdown_path),
        "markdown": markdown[:INLINE_LIMIT] if truncated else markdown,
        "truncated": truncated,
    }
