"""Tests for `moodle panopto list`, `download` and `get`."""

from __future__ import annotations

from pathlib import Path

import pytest
from moodle_cli_panopto import cli as cli_module
from moodle_cli_panopto.cli import app
from moodle_cli_panopto.fetch import TranscriptContent, TranscriptOutcome
from moodle_cli_panopto.recordings import Recording
from typer.testing import CliRunner

from moodle_cli.models import Course

runner = CliRunner()


def _course() -> Course:
    return Course(id=1, shortname="IOS460", fullname="IOS460")


def _recording(delivery_id: str = "aaa", name: str = "Clase 1") -> Recording:
    return Recording(id=delivery_id, name=name, host="campus.hosted.panopto.com")


# -- list --------------------------------------------------------------------------


def test_list_command_prints_id_and_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli_module,
        "list_course_recordings",
        lambda course: (_course(), [_recording("aaa", "Clase 1")]),
    )

    result = runner.invoke(app, ["list", "IOS460"])

    assert result.exit_code == 0
    assert "aaa" in result.stdout
    assert "Clase 1" in result.stdout


def test_list_command_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli_module,
        "list_course_recordings",
        lambda course: (_course(), [_recording("aaa", "Clase 1")]),
    )

    result = runner.invoke(app, ["list", "IOS460", "--json"])

    assert result.exit_code == 0
    assert '"aaa"' in result.stdout


def test_list_command_reports_no_recordings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli_module, "list_course_recordings", lambda course: (_course(), []))

    result = runner.invoke(app, ["list", "IOS460"])

    assert result.exit_code == 0
    assert "No recordings" in result.stdout


# -- get ---------------------------------------------------------------------------


def test_get_command_prints_markdown_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        cli_module,
        "get_transcript",
        lambda course, session, language=None: TranscriptContent(
            recording=_recording(), markdown="# Clase 1\n\n**00:00:00**\nHola.\n"
        ),
    )

    result = runner.invoke(app, ["get", "IOS460", "Clase 1"])

    assert result.exit_code == 0
    assert "Hola." in result.stdout
    assert list(tmp_path.rglob("*.md")) == []


def test_get_command_reports_a_clean_error_on_ambiguity(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_ambiguous(
        course: str, session: str, language: int | None = None
    ) -> TranscriptContent:
        raise ValueError(f"{session!r} is ambiguous; matches: Clase 1, Clase 2")

    monkeypatch.setattr(cli_module, "get_transcript", raise_ambiguous)

    result = runner.invoke(app, ["get", "IOS460", "Clase"])

    assert result.exit_code == 1
    assert "Error" in result.output


def test_get_command_passes_the_language_option(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_get_transcript(
        course: str, session: str, language: int | None = None
    ) -> TranscriptContent:
        seen["language"] = language
        return TranscriptContent(recording=_recording(), markdown="ok")

    monkeypatch.setattr(cli_module, "get_transcript", fake_get_transcript)

    result = runner.invoke(app, ["get", "IOS460", "Clase 1", "--language", "3"])

    assert result.exit_code == 0
    assert seen["language"] == 3


# -- download ------------------------------------------------------------------------


def test_download_command_streams_outcomes_and_exits_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recordings = [_recording("aaa", "Clase 1"), _recording("bbb", "Clase 2")]
    monkeypatch.setattr(
        cli_module, "list_course_recordings", lambda course: (_course(), recordings)
    )
    monkeypatch.setattr(
        cli_module,
        "download_transcripts",
        lambda resolved, selected, **kwargs: iter(
            [
                TranscriptOutcome(
                    recording=recordings[0], destination=Path("a.md"), status="downloaded"
                ),
                TranscriptOutcome(
                    recording=recordings[1], destination=Path("b.md"), status="skipped"
                ),
            ]
        ),
    )

    result = runner.invoke(app, ["download", "IOS460"])

    assert result.exit_code == 0
    assert "ok" in result.stdout
    assert "skip" in result.stdout


def test_download_command_exits_nonzero_on_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    recordings = [_recording("aaa", "Clase 1")]
    monkeypatch.setattr(
        cli_module, "list_course_recordings", lambda course: (_course(), recordings)
    )
    monkeypatch.setattr(
        cli_module,
        "download_transcripts",
        lambda resolved, selected, **kwargs: iter(
            [
                TranscriptOutcome(
                    recording=recordings[0], destination=None, status="error", error="boom"
                )
            ]
        ),
    )

    result = runner.invoke(app, ["download", "IOS460"])

    assert result.exit_code == 1


def test_download_command_rejects_selectors_matching_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli_module, "list_course_recordings", lambda course: (_course(), [_recording()])
    )

    result = runner.invoke(app, ["download", "IOS460", "--session", "no such session"])

    assert result.exit_code == 1
    assert "Error" in result.output


def test_download_command_passes_options_through(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}
    recording = _recording("aaa", "Clase 1")
    monkeypatch.setattr(
        cli_module, "list_course_recordings", lambda course: (_course(), [recording])
    )

    def fake_download_transcripts(
        resolved: Course, selected: list[Recording], **kwargs: object
    ) -> object:
        seen.update(kwargs)
        seen["selected"] = selected
        return iter(
            [TranscriptOutcome(recording=recording, destination=Path("a.md"), status="downloaded")]
        )

    monkeypatch.setattr(cli_module, "download_transcripts", fake_download_transcripts)

    result = runner.invoke(
        app,
        [
            "download",
            "IOS460",
            "--session",
            "aaa",
            "--language",
            "3",
            "--dry-run",
            "--overwrite",
        ],
    )

    assert result.exit_code == 0
    assert seen["language"] == 3
    assert seen["dry_run"] is True
    assert seen["overwrite"] is True
    assert seen["selected"] == [recording]
