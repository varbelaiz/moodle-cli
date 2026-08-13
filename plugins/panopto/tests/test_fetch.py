"""Tests for the orchestration layer -- what this plugin does with a Moodle client and
a Panopto session's answers, not the client or the session themselves.

`open_client` and `moodle_login.login` are both faked/monkeypatched, exactly the split
`moodle_cli_anydoc.tests.test_fetch` uses: resolving course contents and logging in
exercise machinery already tested on its own (`test_moodle_login.py`, core's own
tests). The HTTP this module is genuinely responsible for -- the recordings ajax call,
the LTI relay, DeliveryInfo/GenerateSRT -- goes through respx.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import respx
from moodle_cli_panopto import fetch as fetch_module
from moodle_cli_panopto import lti
from moodle_cli_panopto.fetch import (
    download_transcripts,
    get_transcript,
    get_transcript_and_save,
    list_course_recordings,
)
from moodle_cli_panopto.moodle_login import MoodleWebSession
from moodle_cli_panopto.recordings import Recording

from conftest import BASE_URL, PANOPTO_URL, recording_link, recordings_fragment
from moodle_cli.models import Course, Module, Section

AJAX_URL = f"{BASE_URL}/lib/ajax/service.php"
LAUNCH_URL = f"{BASE_URL}/mod/lti/launch.php"
PANOPTO_ACTION = f"{PANOPTO_URL}/Panopto/lti/lti.aspx"
DELIVERY_INFO_URL = f"{PANOPTO_URL}/Panopto/Pages/Viewer/DeliveryInfo.aspx"
GENERATE_SRT_URL = f"{PANOPTO_URL}/Panopto/Pages/Transcription/GenerateSRT.ashx"

DELIVERY_A = "11111111-1111-1111-1111-111111111111"
DELIVERY_B = "22222222-2222-2222-2222-222222222222"


class FakeWsClient:
    def __init__(self, contents: list[Section], resolved: Course, base_url: str = BASE_URL) -> None:
        self.token = "test-token"
        self.base_url = base_url
        self._contents = contents
        self._resolved = resolved

    def __enter__(self) -> FakeWsClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def resolve_course(self, course: str) -> Course:
        return self._resolved

    def get_course_contents(self, course_id: int) -> list[Section]:
        return self._contents


def _course() -> Course:
    return Course(id=1, shortname="IOS460", fullname="IOS460")


def _sections_with_panopto_lti(cmid: int = 20) -> list[Section]:
    lti_module = Module(id=cmid, name="Clases Grabadas", modname="lti")
    return [Section(id=1, name="General", section=0, modules=[lti_module])]


def _fake_recording(delivery_id: str, name: str) -> Recording:
    return Recording(id=delivery_id, name=name, host="campus.hosted.panopto.com")


@pytest.fixture(autouse=True)
def _reset_cache() -> Iterator[None]:
    lti.reset_cache()
    yield
    lti.reset_cache()


@pytest.fixture
def credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """`open_context` requires MOODLE_USER/MOODLE_PASS even though login() itself is faked."""
    monkeypatch.setenv("MOODLE_URL", BASE_URL)
    monkeypatch.setenv("MOODLE_USER", "ana")
    monkeypatch.setenv("MOODLE_PASS", "hunter2")


@pytest.fixture
def tmp_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    resolved = tmp_path.resolve()
    monkeypatch.chdir(resolved)
    return resolved


def _fake_login(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        fetch_module,
        "login",
        lambda base_url, username, password: MoodleWebSession(
            client=httpx.Client(base_url=BASE_URL), sesskey="sess-1"
        ),
    )


def _mock_transcript_chain(
    *, launch_cmid: int = 20, srt_text: str = "1\n00:00:00,000 --> 00:00:01,000\nHola\n"
) -> None:
    respx.get(LAUNCH_URL, params={"id": str(launch_cmid)}).mock(
        return_value=httpx.Response(
            200,
            text=(
                f'<form name="f" action="{PANOPTO_ACTION}" method="post">'
                '<input type="hidden" name="oauth_signature" value="sig"/></form>'
                "<script>document.f.submit();</script>"
            ),
        )
    )
    respx.post(PANOPTO_ACTION).mock(return_value=httpx.Response(200))
    respx.post(DELIVERY_INFO_URL).mock(
        return_value=httpx.Response(200, json={"Delivery": {"AvailableLanguages": [3]}})
    )
    respx.get(GENERATE_SRT_URL).mock(return_value=httpx.Response(200, text=srt_text))


# -- list_course_recordings -------------------------------------------------------------


def test_list_course_recordings_never_reaches_a_panopto_host(
    monkeypatch: pytest.MonkeyPatch, credentials: None
) -> None:
    """No route is registered for any Panopto host -- if this reached one, respx would
    raise for the unmocked request rather than let it through."""
    ws = FakeWsClient([], _course())
    monkeypatch.setattr(fetch_module, "open_client", lambda: ws)
    _fake_login(monkeypatch)
    fragment = recordings_fragment(recording_link(DELIVERY_A, "Clase 1"))

    with respx.mock:
        respx.post(AJAX_URL).mock(
            return_value=httpx.Response(200, json=[{"error": False, "data": fragment}])
        )
        resolved, recordings = list_course_recordings("IOS460")

    assert resolved.shortname == "IOS460"
    assert [r.id for r in recordings] == [DELIVERY_A]


# -- get_transcript / get_transcript_and_save --------------------------------------------


def test_get_transcript_returns_markdown_without_writing_a_file(
    monkeypatch: pytest.MonkeyPatch, credentials: None, tmp_cwd: Path
) -> None:
    ws = FakeWsClient(_sections_with_panopto_lti(), _course())
    monkeypatch.setattr(fetch_module, "open_client", lambda: ws)
    _fake_login(monkeypatch)
    fragment = recordings_fragment(recording_link(DELIVERY_A, "Clase 1"))

    with respx.mock:
        respx.post(AJAX_URL).mock(
            return_value=httpx.Response(200, json=[{"error": False, "data": fragment}])
        )
        _mock_transcript_chain()
        result = get_transcript("IOS460", "Clase 1")

    assert "Hola" in result.markdown
    assert result.recording.id == DELIVERY_A
    assert list(tmp_cwd.rglob("*.md")) == []


def test_get_transcript_and_save_writes_the_markdown_file(
    monkeypatch: pytest.MonkeyPatch, credentials: None, tmp_cwd: Path
) -> None:
    ws = FakeWsClient(_sections_with_panopto_lti(), _course())
    monkeypatch.setattr(fetch_module, "open_client", lambda: ws)
    _fake_login(monkeypatch)
    fragment = recordings_fragment(recording_link(DELIVERY_A, "Clase 1"))

    with respx.mock:
        respx.post(AJAX_URL).mock(
            return_value=httpx.Response(200, json=[{"error": False, "data": fragment}])
        )
        _mock_transcript_chain()
        result = get_transcript_and_save("IOS460", "Clase 1")

    assert result.markdown_path.resolve() == tmp_cwd / "IOS460" / "Panopto" / "Clase 1.md"
    assert result.markdown_path.read_text(encoding="utf-8") == result.markdown


# -- download_transcripts -----------------------------------------------------------------


def test_download_transcripts_dry_run_makes_no_network_calls(tmp_cwd: Path) -> None:
    """dry_run never opens a session at all -- an empty respx.mock proves it."""
    resolved = _course()
    selected = [
        _fake_recording(DELIVERY_A, "Clase 1"),
        _fake_recording(DELIVERY_B, "Clase 2"),
    ]

    with respx.mock:
        outcomes = list(download_transcripts(resolved, selected, dry_run=True))

    assert [o.status for o in outcomes] == ["planned", "planned"]
    destination = outcomes[0].destination
    assert destination is not None
    assert destination.resolve() == tmp_cwd / "IOS460" / "Panopto" / "Clase 1.md"


def test_download_transcripts_dedupes_a_shared_display_name(tmp_cwd: Path) -> None:
    resolved = _course()
    selected = [
        _fake_recording(DELIVERY_A, "Clase repetida"),
        _fake_recording(DELIVERY_B, "Clase repetida"),
    ]

    with respx.mock:
        outcomes = list(download_transcripts(resolved, selected, dry_run=True))

    destinations = {o.destination for o in outcomes}
    assert len(destinations) == 2, "two different recordings must not collapse to one file"


def test_download_transcripts_skips_an_existing_file_without_overwrite(
    tmp_cwd: Path,
) -> None:
    resolved = _course()
    recording = _fake_recording(DELIVERY_A, "Clase 1")
    destination = tmp_cwd / "IOS460" / "Panopto" / "Clase 1.md"
    destination.parent.mkdir(parents=True)
    destination.write_text("already here", encoding="utf-8")

    with respx.mock:  # no routes registered: a fetch attempt would raise
        outcomes = list(download_transcripts(resolved, [recording]))

    assert len(outcomes) == 1
    assert outcomes[0].status == "skipped"
    assert outcomes[0].destination is not None
    assert outcomes[0].destination.resolve() == destination


def test_download_transcripts_overwrite_refetches_an_existing_file(
    monkeypatch: pytest.MonkeyPatch, credentials: None, tmp_cwd: Path
) -> None:
    ws = FakeWsClient(_sections_with_panopto_lti(), resolved := _course())
    monkeypatch.setattr(fetch_module, "open_client", lambda: ws)
    _fake_login(monkeypatch)
    recording = _fake_recording(DELIVERY_A, "Clase 1")
    destination = tmp_cwd / "IOS460" / "Panopto" / "Clase 1.md"
    destination.parent.mkdir(parents=True)
    destination.write_text("stale", encoding="utf-8")

    with respx.mock:
        _mock_transcript_chain(srt_text="1\n00:00:00,000 --> 00:00:01,000\nFresco\n")
        outcomes = list(download_transcripts(resolved, [recording], overwrite=True))

    assert outcomes[0].status == "downloaded"
    assert "Fresco" in destination.read_text(encoding="utf-8")


def test_download_transcripts_one_failure_does_not_abort_the_batch(
    monkeypatch: pytest.MonkeyPatch, credentials: None, tmp_cwd: Path
) -> None:
    ws = FakeWsClient(_sections_with_panopto_lti(), resolved := _course())
    monkeypatch.setattr(fetch_module, "open_client", lambda: ws)
    _fake_login(monkeypatch)
    good = _fake_recording(DELIVERY_A, "Clase buena")
    bad = _fake_recording(DELIVERY_B, "Clase con falla")

    with respx.mock:
        respx.get(LAUNCH_URL, params={"id": "20"}).mock(
            return_value=httpx.Response(
                200,
                text=(
                    f'<form name="f" action="{PANOPTO_ACTION}" method="post">'
                    '<input type="hidden" name="oauth_signature" value="sig"/></form>'
                    "<script>document.f.submit();</script>"
                ),
            )
        )
        respx.post(PANOPTO_ACTION).mock(return_value=httpx.Response(200))
        respx.post(DELIVERY_INFO_URL).mock(
            return_value=httpx.Response(200, json={"Delivery": {"AvailableLanguages": [3]}})
        )
        # Both recordings ask the same GenerateSRT URL; alternate empty/real per call.
        respx.get(GENERATE_SRT_URL).mock(
            side_effect=[
                httpx.Response(200, text="1\n00:00:00,000 --> 00:00:01,000\nHola\n"),
                httpx.Response(200, text=""),
            ]
        )
        outcomes = list(download_transcripts(resolved, [good, bad]))

    assert [o.status for o in outcomes] == ["downloaded", "error"]
    assert outcomes[1].error is not None
