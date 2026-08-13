"""Orchestration: the one module ``cli.py``/``tools.py`` import from.

Each public function opens its own login and WS client for the call it serves.
``download_transcripts`` is the one exception, sharing a single Panopto session across
its whole batch -- establishing one costs a full LTI relay round trip, not worth paying
once per recording.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from moodle_cli.client import MoodleClient
from moodle_cli.config import load_config
from moodle_cli.downloads import sanitize
from moodle_cli.models import Course
from moodle_cli.session import open_client
from moodle_cli_panopto import lti, panopto_api, srt
from moodle_cli_panopto.errors import PanoptoError
from moodle_cli_panopto.moodle_login import MoodleWebSession, login
from moodle_cli_panopto.recordings import Recording, list_recordings, resolve_session


@dataclass
class RunContext:
    ws: MoodleClient
    moodle: MoodleWebSession

    @property
    def base_url(self) -> str:
        return self.ws.base_url


@contextmanager
def open_context() -> Iterator[RunContext]:
    """Open one WS client plus one Moodle cookie session, scoped to one call.

    This plugin cannot run on a bare ``MOODLE_TOKEN``: the web-service token covers
    none of what it needs (the recordings block, the LTI launch), so
    ``MOODLE_USER``/``MOODLE_PASS`` are required up front, not discovered partway
    through a call.
    """
    config = load_config()
    if not (config.username and config.password):
        raise PanoptoError(
            "panopto needs MOODLE_USER and MOODLE_PASS -- the web-service token alone "
            "cannot reach the Panopto integration"
        )
    with open_client() as ws:
        moodle = login(config.base_url, config.username, config.password)
        try:
            yield RunContext(ws=ws, moodle=moodle)
        finally:
            moodle.client.close()


@dataclass(frozen=True)
class TranscriptContent:
    recording: Recording
    markdown: str


@dataclass(frozen=True)
class TranscriptResult:
    recording: Recording
    markdown: str
    markdown_path: Path


@dataclass(frozen=True)
class TranscriptOutcome:
    recording: Recording
    destination: Path | None
    status: Literal["downloaded", "skipped", "planned", "error"]
    error: str | None = None


def list_course_recordings(course: str) -> tuple[Course, list[Recording]]:
    """Resolve COURSE and list its Panopto recordings. Never reaches a Panopto host."""
    with open_context() as ctx:
        resolved = ctx.ws.resolve_course(course)
        recordings = list_recordings(ctx.moodle, resolved.id)
    return resolved, recordings


def _transcript_markdown(
    ctx: RunContext, resolved: Course, recording: Recording, language: int | None
) -> str:
    panopto, _host = lti.establish_panopto_session(ctx.moodle, ctx.ws, ctx.base_url, resolved.id)
    try:
        info = panopto_api.get_delivery_info(panopto, recording.id)
        resolved_language = panopto_api.resolve_language(info, language)
        raw = panopto_api.fetch_srt(panopto, recording.id, resolved_language)
    finally:
        panopto.close()
    cues = srt.parse_srt(raw)
    return srt.to_markdown(cues, title=recording.name)


def get_transcript(course: str, session: str, *, language: int | None = None) -> TranscriptContent:
    """Fetch one session's transcript. No disk write -- used by ``panopto get``."""
    with open_context() as ctx:
        resolved = ctx.ws.resolve_course(course)
        recordings = list_recordings(ctx.moodle, resolved.id)
        recording = resolve_session(recordings, session)
        markdown = _transcript_markdown(ctx, resolved, recording, language)
    return TranscriptContent(recording=recording, markdown=markdown)


def _destination(resolved: Course, recording: Recording, output: Path | None) -> Path:
    root = output or Path(sanitize(resolved.shortname, fallback=str(resolved.id))) / "Panopto"
    filename = sanitize(recording.name, fallback=recording.id) + ".md"
    return root / filename


def get_transcript_and_save(
    course: str, session: str, *, language: int | None = None, output: Path | None = None
) -> TranscriptResult:
    """Fetch one session's transcript and write it to disk. Used by the MCP
    ``get_transcript`` tool."""
    with open_context() as ctx:
        resolved = ctx.ws.resolve_course(course)
        recordings = list_recordings(ctx.moodle, resolved.id)
        recording = resolve_session(recordings, session)
        markdown = _transcript_markdown(ctx, resolved, recording, language)

    destination = _destination(resolved, recording, output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(markdown, encoding="utf-8")
    return TranscriptResult(recording=recording, markdown=markdown, markdown_path=destination)


def _claim_destination(destination: Path, identity: str, claimed: dict[Path, str]) -> Path | None:
    """Resolve DESTINATION against the paths already claimed by this batch.

    Collapses to one entry when the identity (the delivery id) already claimed there is
    the same; renames the second when two recordings share a display name but are
    genuinely different. Mirrors ``moodle_cli.downloads._claim``, keyed by a string
    delivery id rather than an int module id -- that helper cannot be reused as-is.
    """
    candidate = destination
    suffix = 0
    while True:
        existing = claimed.get(candidate)
        if existing is None:
            claimed[candidate] = identity
            return candidate
        if existing == identity:
            return None
        suffix += 1
        tag = identity[:8] if suffix == 1 else f"{identity[:8]}-{suffix}"
        candidate = destination.with_name(f"{destination.stem} ({tag}){destination.suffix}")


def download_transcripts(
    resolved: Course,
    selected: list[Recording],
    *,
    language: int | None = None,
    output: Path | None = None,
    overwrite: bool = False,
    dry_run: bool = False,
) -> Iterator[TranscriptOutcome]:
    """Fetch and write every recording in SELECTED, one Panopto session for the whole batch.

    One recording failing does not stop the rest. ``dry_run`` never opens a Panopto
    session at all -- planning destinations is free, the same as
    ``moodle_cli.downloads.plan_downloads``.
    """
    claimed: dict[Path, str] = {}
    planned: list[tuple[Recording, Path]] = []
    for recording in selected:
        destination = _claim_destination(
            _destination(resolved, recording, output), recording.id, claimed
        )
        if destination is None:
            continue
        planned.append((recording, destination))

    if dry_run:
        for recording, destination in planned:
            yield TranscriptOutcome(recording=recording, destination=destination, status="planned")
        return

    to_fetch = []
    for recording, destination in planned:
        if not overwrite and destination.exists() and destination.stat().st_size:
            yield TranscriptOutcome(recording=recording, destination=destination, status="skipped")
            continue
        to_fetch.append((recording, destination))

    if not to_fetch:
        return

    with open_context() as ctx:
        panopto, _host = lti.establish_panopto_session(
            ctx.moodle, ctx.ws, ctx.base_url, resolved.id
        )
        try:
            for recording, destination in to_fetch:
                try:
                    info = panopto_api.get_delivery_info(panopto, recording.id)
                    resolved_language = panopto_api.resolve_language(info, language)
                    raw = panopto_api.fetch_srt(panopto, recording.id, resolved_language)
                    cues = srt.parse_srt(raw)
                    markdown = srt.to_markdown(cues, title=recording.name)
                except (PanoptoError, ValueError, srt.SrtError) as exc:
                    yield TranscriptOutcome(
                        recording=recording,
                        destination=destination,
                        status="error",
                        error=str(exc),
                    )
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(markdown, encoding="utf-8")
                yield TranscriptOutcome(
                    recording=recording, destination=destination, status="downloaded"
                )
        finally:
            panopto.close()


__all__ = [
    "RunContext",
    "TranscriptContent",
    "TranscriptOutcome",
    "TranscriptResult",
    "download_transcripts",
    "get_transcript",
    "get_transcript_and_save",
    "list_course_recordings",
    "open_context",
]
