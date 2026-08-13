"""Converting a single file already on disk to markdown.

Local conversion never touches the network: anydoc raises on the file itself, with an
exception type that names what went wrong (encrypted, malformed, unsupported format,
...). The `ocr=True` path is the exception -- it sends the file to Firecrawl Parse, an
opt-in only a caller who explicitly asks for it reaches.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from moodle_cli_anydoc.hosted import HostedError, convert_hosted, resolve_firecrawl_key


class ConversionError(Exception):
    """A file could not be converted to markdown."""


@dataclass(frozen=True)
class Converted:
    source: Path
    markdown: str
    markdown_path: Path


def convert_file(source: Path, *, ocr: bool = False) -> Converted:
    """Convert SOURCE to markdown and write it to `<name>.md` alongside it.

    Appends rather than replaces the suffix: this campus has courses where a teacher
    uploads the same material as both '.pdf' and '.docx' under one stem, and replacing
    the suffix would make the second conversion overwrite the first.

    `ocr=True` sends the file to Firecrawl Parse (hosted, OCR-capable) instead of
    converting it locally -- an explicit choice, not a fallback, since it means a
    third-party service sees the file. Raises if `FIRECRAWL_KEY` is not configured
    rather than silently converting locally instead.
    """
    if not source.is_file():
        raise ConversionError(f"{source}: no such file")

    if ocr:
        api_key = resolve_firecrawl_key()
        if not api_key:
            raise ConversionError(
                f"{source}: --ocr requires FIRECRAWL_KEY to be set (environment or .env)"
            )
        try:
            markdown = convert_hosted(source, api_key)
        except HostedError as exc:
            raise ConversionError(f"{source}: {exc}") from exc
    else:
        import anydoc

        try:
            markdown = anydoc.to_markdown(str(source))
        except (anydoc.ConvertError, OSError) as exc:
            raise ConversionError(f"{source}: {exc}") from exc

    markdown_path = source.with_name(f"{source.name}.md")
    try:
        markdown_path.write_text(markdown, encoding="utf-8")
    # Every way out of this function is a ConversionError, so one unwritable destination
    # costs its own file and no more. Left to escape, an OSError here would abort a batch
    # partway and reach the user as a traceback: `main` only turns MoodleError into a
    # clean exit, and a plugin's exception is not one.
    except OSError as exc:
        raise ConversionError(f"{markdown_path}: could not write the markdown ({exc})") from exc
    return Converted(source, markdown, markdown_path)
