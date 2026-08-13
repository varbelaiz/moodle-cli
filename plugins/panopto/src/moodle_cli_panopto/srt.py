"""Parsing Panopto's SRT transcripts and reflowing them into markdown.

Purely mechanical: no network, no I/O, no rewriting of the ASR text itself. "Polishing"
here means grouping cues into paragraphs and marking them with timestamps -- the words
Panopto transcribed are never touched beyond whitespace normalization.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from itertools import pairwise

_TIMESTAMP_RE = re.compile(
    r"(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2}),(\d{3})"
)
#: Panopto repeats this disclaimer as the first line of the first cue only.
_DISCLAIMER_RE = re.compile(r"^\[.*auto-generated transcript.*\]$", re.IGNORECASE)

#: A pause of this many seconds or more between two cues starts a new paragraph.
PAUSE_GAP_SECONDS = 2.0


class SrtError(Exception):
    """Malformed or empty SRT text."""


@dataclass(frozen=True)
class Cue:
    index: int
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Paragraph:
    start: float
    text: str


def _timestamp_to_seconds(hh: str, mm: str, ss: str, ms: str) -> float:
    return int(hh) * 3600 + int(mm) * 60 + int(ss) + int(ms) / 1000


def parse_srt(raw: str) -> list[Cue]:
    """Parse SRT cue blocks: an index line, a timestamp range, then one or more text lines.

    Multi-line cue text is whitespace-joined into one line, never reworded. Raises
    ``SrtError`` if parsing yields zero cues -- the second line of defense after
    ``panopto_api.fetch_srt``'s empty-body check, against a non-empty but garbage body.
    """
    cues: list[Cue] = []
    for block in re.split(r"\r?\n\r?\n+", raw.strip()):
        lines = [line for line in block.splitlines() if line.strip()]
        if len(lines) < 2:
            continue
        try:
            index = int(lines[0].strip())
        except ValueError:
            continue
        match = _TIMESTAMP_RE.search(lines[1])
        if match is None:
            continue
        start = _timestamp_to_seconds(*match.group(1, 2, 3, 4))
        end = _timestamp_to_seconds(*match.group(5, 6, 7, 8))

        text_lines = lines[2:]
        if not cues and text_lines and _DISCLAIMER_RE.match(text_lines[0].strip()):
            text_lines = text_lines[1:]
        text = " ".join(" ".join(line.split()) for line in text_lines).strip()
        if not text:
            continue
        cues.append(Cue(index=index, start=start, end=end, text=text))

    if not cues:
        raise SrtError("no cues found in SRT text")
    return cues


def group_into_paragraphs(cues: list[Cue], *, gap: float = PAUSE_GAP_SECONDS) -> list[Paragraph]:
    """Group consecutive cues into paragraphs, breaking wherever the pause between one
    cue's end and the next cue's start exceeds GAP seconds."""
    if not cues:
        return []
    paragraphs: list[Paragraph] = []
    current_start = cues[0].start
    current_texts = [cues[0].text]
    for previous, cue in pairwise(cues):
        if cue.start - previous.end > gap:
            paragraphs.append(Paragraph(start=current_start, text=" ".join(current_texts)))
            current_start = cue.start
            current_texts = [cue.text]
        else:
            current_texts.append(cue.text)
    paragraphs.append(Paragraph(start=current_start, text=" ".join(current_texts)))
    return paragraphs


def _format_timestamp(seconds: float) -> str:
    total = int(seconds)
    hh, remainder = divmod(total, 3600)
    mm, ss = divmod(remainder, 60)
    return f"{hh:02d}:{mm:02d}:{ss:02d}"


def to_markdown(
    cues: list[Cue], *, title: str | None = None, gap: float = PAUSE_GAP_SECONDS
) -> str:
    """Render CUES as markdown: an optional title heading, then one
    ``**HH:MM:SS**``-marked paragraph per pause-separated group."""
    paragraphs = group_into_paragraphs(cues, gap=gap)
    blocks = [f"# {title}"] if title else []
    blocks.extend(f"**{_format_timestamp(p.start)}**\n{p.text}" for p in paragraphs)
    return "\n\n".join(blocks) + "\n"


__all__ = [
    "PAUSE_GAP_SECONDS",
    "Cue",
    "Paragraph",
    "SrtError",
    "group_into_paragraphs",
    "parse_srt",
    "to_markdown",
]
