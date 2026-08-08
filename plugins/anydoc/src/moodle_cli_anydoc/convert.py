"""Converting a single file already on disk to markdown.

Nothing here touches the network, so there is no HTTP-200-but-actually-an-error case to
guard against: anydoc raises on the file itself, with an exception type that names what
went wrong (encrypted, malformed, unsupported format, ...).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class ConversionError(Exception):
    """A file could not be converted to markdown."""


@dataclass(frozen=True)
class Converted:
    source: Path
    markdown: str
    markdown_path: Path


def convert_file(source: Path) -> Converted:
    """Convert SOURCE to markdown and write it to `<name>.md` alongside it.

    Appends rather than replaces the suffix: this campus has courses where a teacher
    uploads the same material as both '.pdf' and '.docx' under one stem, and replacing
    the suffix would make the second conversion overwrite the first.
    """
    import anydoc

    if not source.is_file():
        raise ConversionError(f"{source}: no such file")
    try:
        markdown = anydoc.to_markdown(str(source))
    except (anydoc.ConvertError, OSError) as exc:
        raise ConversionError(f"{source}: {exc}") from exc

    markdown_path = source.with_name(f"{source.name}.md")
    markdown_path.write_text(markdown, encoding="utf-8")
    return Converted(source, markdown, markdown_path)
