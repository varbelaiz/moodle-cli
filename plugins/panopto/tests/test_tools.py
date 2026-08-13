"""Tests for the `panopto_list_recordings`, `panopto_download_transcript` and
`panopto_get_transcript` MCP tools."""

from __future__ import annotations

from pathlib import Path

import pytest
from moodle_cli_panopto import tools as tools_module
from moodle_cli_panopto.fetch import TranscriptOutcome, TranscriptResult
from moodle_cli_panopto.recordings import Recording
from moodle_cli_panopto.tools import (
    INLINE_LIMIT,
    download_transcript,
    get_transcript,
    list_recordings,
)

from moodle_cli.models import Course


def _course() -> Course:
    return Course(id=1, shortname="IOS460", fullname="IOS460")


def _recording(delivery_id: str = "aaa", name: str = "Clase 1") -> Recording:
    return Recording(id=delivery_id, name=name, host="campus.hosted.panopto.com")


# -- list_recordings -----------------------------------------------------------------


def test_list_recordings_returns_id_and_name_only(monkeypatch: pytest.MonkeyPatch) -> None:
    recordings = [_recording("aaa", "Clase 1"), _recording("bbb", "Clase 2")]
    monkeypatch.setattr(
        tools_module, "list_course_recordings", lambda course: (_course(), recordings)
    )

    assert list_recordings("IOS460") == [
        {"id": "aaa", "name": "Clase 1"},
        {"id": "bbb", "name": "Clase 2"},
    ]


# -- download_transcript ---------------------------------------------------------------


def test_download_transcript_without_session_fetches_every_recording(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recordings = [_recording("aaa", "Clase 1"), _recording("bbb", "Clase 2")]
    monkeypatch.setattr(
        tools_module, "list_course_recordings", lambda course: (_course(), recordings)
    )
    monkeypatch.setattr(
        tools_module,
        "download_transcripts",
        lambda resolved, selected: iter(
            [
                TranscriptOutcome(
                    recording=recordings[0], destination=Path("a.md"), status="downloaded"
                ),
                TranscriptOutcome(
                    recording=recordings[1], destination=None, status="error", error="boom"
                ),
            ]
        ),
    )

    results = download_transcript("IOS460")

    assert results == [
        {"id": "aaa", "name": "Clase 1", "status": "downloaded", "path": "a.md"},
        {"id": "bbb", "name": "Clase 2", "status": "error", "path": None, "error": "boom"},
    ]


def test_download_transcript_with_session_narrows_to_one_recording(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recordings = [_recording("aaa", "Clase 1"), _recording("bbb", "Clase 2")]
    monkeypatch.setattr(
        tools_module, "list_course_recordings", lambda course: (_course(), recordings)
    )
    seen: dict[str, object] = {}

    def fake_download_transcripts(resolved: Course, selected: list[Recording]) -> object:
        seen["selected"] = selected
        return iter(
            [
                TranscriptOutcome(
                    recording=selected[0], destination=Path("b.md"), status="downloaded"
                )
            ]
        )

    monkeypatch.setattr(tools_module, "download_transcripts", fake_download_transcripts)

    results = download_transcript("IOS460", session="bbb")

    assert seen["selected"] == [recordings[1]]
    assert results == [{"id": "bbb", "name": "Clase 2", "status": "downloaded", "path": "b.md"}]


# -- get_transcript ----------------------------------------------------------------------


def test_get_transcript_returns_content_and_path(monkeypatch: pytest.MonkeyPatch) -> None:
    markdown_path = Path("IOS460/Panopto/Clase 1.md")
    monkeypatch.setattr(
        tools_module,
        "get_transcript_and_save",
        lambda course, session, language=None: TranscriptResult(
            recording=_recording(), markdown="# Clase 1\n", markdown_path=markdown_path
        ),
    )

    payload = get_transcript("IOS460", "Clase 1")

    assert payload == {
        "markdown_path": str(markdown_path),
        "markdown": "# Clase 1\n",
        "truncated": False,
    }


def test_get_transcript_truncates_long_output(monkeypatch: pytest.MonkeyPatch) -> None:
    markdown_path = Path("big.md")
    long_markdown = "x" * (INLINE_LIMIT + 500)
    monkeypatch.setattr(
        tools_module,
        "get_transcript_and_save",
        lambda course, session, language=None: TranscriptResult(
            recording=_recording(), markdown=long_markdown, markdown_path=markdown_path
        ),
    )

    payload = get_transcript("IOS460", "Clase 1")

    assert payload["truncated"] is True
    assert len(payload["markdown"]) == INLINE_LIMIT
    assert payload["markdown_path"] == str(markdown_path)


def test_get_transcript_passes_language_through(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_get_transcript_and_save(
        course: str, session: str, language: int | None = None
    ) -> TranscriptResult:
        seen["language"] = language
        return TranscriptResult(recording=_recording(), markdown="ok", markdown_path=Path("a.md"))

    monkeypatch.setattr(tools_module, "get_transcript_and_save", fake_get_transcript_and_save)

    get_transcript("IOS460", "Clase 1", language=3)

    assert seen["language"] == 3
