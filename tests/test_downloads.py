"""Download tests.

The load-bearing cases are the ones where the server returns HTTP 200 but not the file.
Those must fail loudly and leave nothing behind on disk.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from moodle_cli.downloads import (
    DownloadStatus,
    dedupe_extension,
    download_file,
    plan_downloads,
    sanitize,
)
from moodle_cli.errors import DownloadError, MoodleAPIError
from moodle_cli.models import CourseFile, Section

FILE_URL = "https://campus.example.edu/webservice/pluginfile.php/1/mod_resource/content/5/a.pdf"


@pytest.fixture
def sections(contents_payload: list[dict[str, Any]]) -> list[Section]:
    return [Section.model_validate(s) for s in contents_payload]


@pytest.fixture
def pdf() -> CourseFile:
    return CourseFile(
        filename="a.pdf",
        filepath="/",
        filesize=11,
        fileurl=FILE_URL,
        mimetype="application/pdf",
        type="file",
    )


# -- naming ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Programa  de  la  materia", "Programa de la materia"),
        ("unidad/1", "unidad-1"),
        ("Cómputo científico", "Cómputo científico"),
        # Leading dots are stripped too: a name like ".git" would become a hidden file.
        ("  ..trailing..  ", "trailing"),
        ("", "untitled"),
    ],
)
def test_sanitize(raw: str, expected: str) -> None:
    assert sanitize(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Programa.pdf.pdf", "Programa.pdf"),
        ("Programa.pdf", "Programa.pdf"),
        ("Cronograma.pdf - Cronograma.pdf", "Cronograma.pdf - Cronograma.pdf"),
        ("noextension", "noextension"),
    ],
)
def test_dedupe_extension(raw: str, expected: str) -> None:
    assert dedupe_extension(raw) == expected


# -- planning --------------------------------------------------------------------


def test_plan_downloads_mirrors_sections_and_folders(sections: list[Section]) -> None:
    planned = plan_downloads(sections, Path("root"))
    paths = sorted(str(p.destination) for p in planned)

    # "Programa  - Taller.pdf.pdf" loses its doubled extension and its doubled space.
    assert paths == [
        "root/00 - General/Material Bibliográfico Digital/_Carátula licencia.pdf",
        "root/00 - General/Material Bibliográfico Digital/unidad-1/Cap 1.pdf",
        "root/00 - General/Programa - Taller.pdf",
    ]


def test_plan_downloads_excludes_url_modules(sections: list[Section]) -> None:
    assert all(p.module.modname != "url" for p in plan_downloads(sections, Path("root")))


def _duplicate_module(sections: list[Section], *, new_size: int | None = None) -> list[Section]:
    """Clone the resource module, the way a teacher duplicating an activity does."""
    original = next(m for m in sections[0].modules if m.modname == "resource")
    clone = original.model_copy(deep=True)
    clone.id = original.id + 900_000
    if new_size is not None:
        clone.contents[0].filesize = new_size
    sections[0].modules.append(clone)
    return sections


def test_plan_downloads_collapses_byte_identical_duplicates(sections: list[Section]) -> None:
    """A duplicated activity pointing at the same file must not be planned twice."""
    planned = plan_downloads(_duplicate_module(sections), Path("root"))
    destinations = [p.destination for p in planned]

    assert len(destinations) == len(set(destinations))
    assert sum(1 for d in destinations if d.name == "Programa - Taller.pdf") == 1


def test_plan_downloads_renames_rather_than_overwrites_differing_files(
    sections: list[Section],
) -> None:
    """Same name, different bytes: keep both instead of silently losing one."""
    planned = plan_downloads(_duplicate_module(sections, new_size=999), Path("root"))
    names = sorted(p.destination.name for p in planned if "Taller" in p.destination.name)

    assert names == ["Programa - Taller (900002).pdf", "Programa - Taller.pdf"]
    assert len({p.destination for p in planned}) == len(planned)


def test_plan_downloads_filters_by_section(sections: list[Section]) -> None:
    assert plan_downloads(sections, Path("root"), only_sections={1}) == []


def test_plan_downloads_filters_by_module_type(sections: list[Section]) -> None:
    planned = plan_downloads(sections, Path("root"), only_modtypes={"resource"})
    assert len(planned) == 1
    assert planned[0].module.modname == "resource"


# -- transfer --------------------------------------------------------------------


@respx.mock
def test_download_file_writes_and_reports_size(pdf: CourseFile, tmp_path: Path) -> None:
    respx.get(FILE_URL).mock(return_value=httpx.Response(200, content=b"hello world"))
    destination = tmp_path / "a.pdf"

    with httpx.Client() as http:
        result = download_file(http, pdf, "tok", destination)

    assert result.status is DownloadStatus.DOWNLOADED
    assert destination.read_bytes() == b"hello world"


@respx.mock
def test_download_file_sends_the_token(pdf: CourseFile, tmp_path: Path) -> None:
    route = respx.get(FILE_URL).mock(return_value=httpx.Response(200, content=b"hello world"))
    with httpx.Client() as http:
        download_file(http, pdf, "secret-token", tmp_path / "a.pdf")
    assert route.calls[0].request.url.params["token"] == "secret-token"


@respx.mock
def test_download_file_rejects_json_error_served_as_200(pdf: CourseFile, tmp_path: Path) -> None:
    """The trap: pluginfile.php answers a missing token with 200 and a JSON body."""
    respx.get(FILE_URL).mock(
        return_value=httpx.Response(
            200,
            json={"error": "Un parámetro necesario (token) faltaba", "errorcode": "missingparam"},
        )
    )
    destination = tmp_path / "a.pdf"

    with httpx.Client() as http, pytest.raises(MoodleAPIError, match="missingparam"):
        download_file(http, pdf, "tok", destination)

    assert not destination.exists()
    assert list(tmp_path.glob("*.part")) == []


@respx.mock
def test_download_file_rejects_size_mismatch(pdf: CourseFile, tmp_path: Path) -> None:
    respx.get(FILE_URL).mock(return_value=httpx.Response(200, content=b"truncated"))
    destination = tmp_path / "a.pdf"

    with httpx.Client() as http, pytest.raises(DownloadError, match="expected 11 bytes"):
        download_file(http, pdf, "tok", destination)

    assert not destination.exists()
    assert list(tmp_path.glob("*.part")) == []


@respx.mock
def test_download_file_allows_a_genuinely_json_file(tmp_path: Path) -> None:
    """A JSON content-type is only suspicious when the file itself is not JSON."""
    payload = b'{"real": "data"}'
    respx.get(FILE_URL).mock(
        return_value=httpx.Response(
            200, content=payload, headers={"content-type": "application/json"}
        )
    )
    json_file = CourseFile(
        filename="data.json",
        filesize=len(payload),
        fileurl=FILE_URL,
        mimetype="application/json",
        type="file",
    )

    with httpx.Client() as http:
        result = download_file(http, json_file, "tok", tmp_path / "data.json")

    assert result.status is DownloadStatus.DOWNLOADED


@respx.mock
def test_download_file_skips_when_size_already_matches(pdf: CourseFile, tmp_path: Path) -> None:
    route = respx.get(FILE_URL).mock(return_value=httpx.Response(200, content=b"hello world"))
    destination = tmp_path / "a.pdf"
    destination.write_bytes(b"hello world")

    with httpx.Client() as http:
        result = download_file(http, pdf, "tok", destination)

    assert result.status is DownloadStatus.SKIPPED
    assert route.call_count == 0


@respx.mock
def test_download_file_redownloads_a_truncated_local_file(pdf: CourseFile, tmp_path: Path) -> None:
    respx.get(FILE_URL).mock(return_value=httpx.Response(200, content=b"hello world"))
    destination = tmp_path / "a.pdf"
    destination.write_bytes(b"partial")

    with httpx.Client() as http:
        result = download_file(http, pdf, "tok", destination)

    assert result.status is DownloadStatus.DOWNLOADED
    assert destination.read_bytes() == b"hello world"


def test_download_file_requires_a_url(tmp_path: Path) -> None:
    linkless = CourseFile(filename="x.pdf", type="file")
    with httpx.Client() as http, pytest.raises(DownloadError, match="no download URL"):
        download_file(http, linkless, "tok", tmp_path / "x.pdf")
