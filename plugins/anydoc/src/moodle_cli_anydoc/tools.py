"""The MCP-facing conversion tool, registered as `anydoc_convert`.

Returns the markdown inline as well as the path it was written to: a convert-then-read
round trip is exactly the extra call an agent reaching for this tool is trying to avoid.
`truncated` guards the case the core server's own tools avoid entirely by never returning
content -- a large PDF converts to more markdown than belongs inline in one response --
without giving up the inline text for the common case, which is a course handout of a
few pages.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from moodle_cli_anydoc.convert import convert_file

INLINE_LIMIT = 20_000


def convert(path: str) -> dict[str, Any]:
    """Convert a course file already on disk to markdown.

    `path` is a file `course download` (or `download_course_files`) put on disk, not a
    course or file identifier -- this tool never reaches the campus. Writes the result to
    `<path>.md` and always returns that full path; `markdown` is capped at 20,000
    characters, with `truncated` true when the file's own contents run longer -- read
    `markdown_path` for the rest.

    Raises if `path` does not exist or cannot be converted -- encrypted, corrupt, or an
    unsupported format.
    """
    result = convert_file(Path(path))
    markdown = result.markdown
    truncated = len(markdown) > INLINE_LIMIT
    return {
        "path": str(result.source),
        "markdown_path": str(result.markdown_path),
        "markdown": markdown[:INLINE_LIMIT] if truncated else markdown,
        "truncated": truncated,
    }
