"""Tests for fetching and converting a single course file.

The client is faked rather than routed through respx: resolving a course exercises
several webservice calls that add nothing here, since what is under test is what this
plugin does with a client's answers, not the client itself. The file download does go
through respx -- that part is a plain HTTP GET this plugin is genuinely responsible for.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx
from moodle_cli_anydoc import fetch as fetch_module
from moodle_cli_anydoc.fetch import fetch_and_convert

from conftest import BASE_URL
from moodle_cli.models import Course, CourseFile, Module, Section


def _course() -> Course:
    return Course(id=1, shortname="IOS460", fullname="IOS460")


def _file(name: str, size: int, url: str) -> CourseFile:
    return CourseFile(
        filename=name, filepath="/", filesize=size, fileurl=url, mimetype="text/csv", type="file"
    )


def _section(number: int, *files: tuple[str, int, str], module_id: int = 10) -> Section:
    modules = [
        Module(id=module_id + i, name=name, modname="resource", contents=[_file(name, size, url)])
        for i, (name, size, url) in enumerate(files)
    ]
    return Section(id=number, name=f"Section {number}", section=number, modules=modules)


class FakeClient:
    """Stands in for MoodleClient: resolve_course and get_course_contents, dictated by
    the test, plus the context-manager protocol fetch_and_convert uses."""

    def __init__(self, contents: list[Section], resolved: Course) -> None:
        self.token = "test-token"
        self._contents = contents
        self._resolved = resolved

    def __enter__(self) -> FakeClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def resolve_course(self, course: str) -> Course:
        return self._resolved

    def get_course_contents(self, course_id: int) -> list[Section]:
        return self._contents


@pytest.fixture
def tmp_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    resolved = tmp_path.resolve()
    monkeypatch.chdir(resolved)
    return resolved


def test_fetch_and_convert_downloads_and_converts(
    tmp_cwd: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = f"{BASE_URL}/webservice/pluginfile.php/1/mod_resource/content/1/grades.csv"
    body = b"a,b\n1,2\n"
    client = FakeClient([_section(1, ("grades.csv", len(body), url))], _course())
    monkeypatch.setattr(fetch_module, "open_client", lambda: client)

    with respx.mock:
        respx.get(url).mock(return_value=httpx.Response(200, content=body))
        result = fetch_and_convert("IOS460", "grades.csv")

    assert result.source.resolve() == tmp_cwd / "IOS460" / "01 - Section 1" / "grades.csv"
    assert result.markdown_path.exists()
    assert "1" in result.markdown


def test_fetch_and_convert_reuses_an_already_downloaded_file(
    tmp_cwd: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No respx route is registered: a second call must not touch the network at all."""
    url = f"{BASE_URL}/webservice/pluginfile.php/1/mod_resource/content/1/grades.csv"
    body = b"a,b\n1,2\n"
    client = FakeClient([_section(1, ("grades.csv", len(body), url))], _course())
    monkeypatch.setattr(fetch_module, "open_client", lambda: client)

    destination = tmp_cwd / "IOS460" / "01 - Section 1" / "grades.csv"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(body)

    with respx.mock:
        result = fetch_and_convert("IOS460", "grades.csv")

    assert result.source.resolve() == destination


def test_fetch_and_convert_raises_when_no_file_matches(
    tmp_cwd: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = FakeClient([_section(1)], _course())
    monkeypatch.setattr(fetch_module, "open_client", lambda: client)

    with pytest.raises(ValueError, match="no such file"):
        fetch_and_convert("IOS460", "missing.pdf")


def test_fetch_and_convert_raises_when_the_name_is_ambiguous(
    tmp_cwd: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two sections, same filename, different sizes -- this campus does this in H202."""
    url_a = f"{BASE_URL}/webservice/pluginfile.php/1/mod_resource/content/1/notes.csv"
    url_b = f"{BASE_URL}/webservice/pluginfile.php/1/mod_resource/content/2/notes.csv"
    sections = [
        _section(1, ("notes.csv", 10, url_a), module_id=10),
        _section(2, ("notes.csv", 20, url_b), module_id=20),
    ]
    client = FakeClient(sections, _course())
    monkeypatch.setattr(fetch_module, "open_client", lambda: client)

    with pytest.raises(ValueError, match="matches 2 files"):
        fetch_and_convert("IOS460", "notes.csv")


def test_fetch_and_convert_narrows_an_ambiguous_name_with_section(
    tmp_cwd: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url_a = f"{BASE_URL}/webservice/pluginfile.php/1/mod_resource/content/1/notes.csv"
    url_b = f"{BASE_URL}/webservice/pluginfile.php/1/mod_resource/content/2/notes.csv"
    body = b"a,b\n1,2\n"
    sections = [
        _section(1, ("notes.csv", 10, url_a), module_id=10),
        _section(2, ("notes.csv", len(body), url_b), module_id=20),
    ]
    client = FakeClient(sections, _course())
    monkeypatch.setattr(fetch_module, "open_client", lambda: client)

    with respx.mock:
        respx.get(url_b).mock(return_value=httpx.Response(200, content=body))
        result = fetch_and_convert("IOS460", "notes.csv", section=2)

    assert result.source.resolve() == tmp_cwd / "IOS460" / "02 - Section 2" / "notes.csv"
