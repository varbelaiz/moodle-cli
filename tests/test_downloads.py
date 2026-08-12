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
    _classify_google_url,
    dedupe_extension,
    download_file,
    download_link,
    plan_downloads,
    plan_link_downloads,
    sanitize,
)
from moodle_cli.errors import DownloadError, MoodleAPIError
from moodle_cli.models import CourseFile, Module, Section

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


def test_plan_downloads_selects_an_exact_filename(sections: list[Section]) -> None:
    planned = plan_downloads(sections, Path("root"), only_names={"Cap 1.pdf"})
    assert [p.file.filename for p in planned] == ["Cap 1.pdf"]


def test_exact_name_does_not_match_partially(sections: list[Section]) -> None:
    """The point of --file is determinism: a substring must not select the file."""
    assert plan_downloads(sections, Path("root"), only_names={"Cap 1"}) == []


def test_plan_downloads_selects_by_glob(sections: list[Section]) -> None:
    planned = plan_downloads(sections, Path("root"), only_patterns=["*.pdf"])
    assert {p.file.filename for p in planned} == {
        "Programa  - Taller.pdf.pdf",
        "_Carátula licencia.pdf",
        "Cap 1.pdf",
    }


def test_glob_is_case_insensitive(sections: list[Section]) -> None:
    assert len(plan_downloads(sections, Path("root"), only_patterns=["*.PDF"])) == 3


def test_name_and_glob_selectors_union(sections: list[Section]) -> None:
    planned = plan_downloads(
        sections, Path("root"), only_names={"Cap 1.pdf"}, only_patterns=["_Car*"]
    )
    assert {p.file.filename for p in planned} == {"Cap 1.pdf", "_Carátula licencia.pdf"}


def test_name_selector_intersects_with_structural_filters(sections: list[Section]) -> None:
    """Selectors compose by intersection: a real file in the wrong section drops out."""
    assert plan_downloads(sections, Path("root"), only_sections={1}, only_names={"Cap 1.pdf"}) == []


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


# -- Google link classification ---------------------------------------------------


@pytest.mark.parametrize(
    ("url", "export_url", "extension"),
    [
        (
            "https://docs.google.com/presentation/d/DOC1/edit?usp=sharing",
            "https://docs.google.com/presentation/d/DOC1/export/pptx",
            "pptx",
        ),
        (
            "https://docs.google.com/document/d/DOC2/edit?usp=sharing",
            "https://docs.google.com/document/d/DOC2/export?format=docx",
            "docx",
        ),
        (
            "https://docs.google.com/spreadsheets/d/DOC3/edit?usp=sharing",
            "https://docs.google.com/spreadsheets/d/DOC3/export?format=xlsx",
            "xlsx",
        ),
    ],
)
def test_classify_native_google_docs(url: str, export_url: str, extension: str) -> None:
    export = _classify_google_url(url)
    assert export is not None
    assert export.export_url == export_url
    assert export.extension == extension
    assert export.drive_id is None


def test_classify_drive_file_has_no_known_extension() -> None:
    export = _classify_google_url("https://drive.google.com/file/d/DRIVE1/view?usp=sharing")
    assert export is not None
    assert export.export_url == "https://drive.google.com/uc?export=download&id=DRIVE1"
    assert export.extension is None
    assert export.drive_id == "DRIVE1"


@pytest.mark.parametrize(
    "url",
    [
        "https://drive.google.com/open?id=DRIVE1",
        "https://drive.google.com/uc?id=DRIVE1",
    ],
)
def test_classify_drive_file_from_a_query_string_id(url: str) -> None:
    """The legacy share-link forms carry the id in the query string, not the path."""
    export = _classify_google_url(url)
    assert export is not None
    assert export.export_url == "https://drive.google.com/uc?export=download&id=DRIVE1"
    assert export.drive_id == "DRIVE1"


def test_classify_colab_notebook_reuses_the_drive_uc_endpoint() -> None:
    export = _classify_google_url("https://colab.research.google.com/drive/COLAB1?usp=sharing")
    assert export is not None
    assert export.export_url == "https://drive.google.com/uc?export=download&id=COLAB1"
    assert export.extension is None
    assert export.drive_id == "COLAB1"


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/example/repo",
        "https://slack.example.com/join",
        "https://claude.ai/public/artifacts/abc",
        "not a url",
    ],
)
def test_classify_non_google_url_returns_none(url: str) -> None:
    assert _classify_google_url(url) is None


# -- planning links ----------------------------------------------------------------


def _link_section(
    *, section_num: int, name: str, url: str, module_id: int = 100, modname: str = "url"
) -> Section:
    return Section(
        id=section_num,
        name=f"Section {section_num}",
        section=section_num,
        modules=[
            Module(
                id=module_id,
                name=name,
                modname=modname,
                contents=[CourseFile(filename=name, filesize=0, fileurl=url, type="url")],
            )
        ],
    )


def test_plan_link_downloads_excludes_non_google_links(sections: list[Section]) -> None:
    """The Slack link in the shared fixture has nothing this app can fetch."""
    assert plan_link_downloads(sections, Path("root")) == []


def test_plan_link_downloads_uses_the_deterministic_export_extension() -> None:
    section = _link_section(
        section_num=1,
        name="Clase 1 - Word Embeddings",
        url="https://docs.google.com/presentation/d/DOC1/edit?usp=sharing",
    )
    planned = plan_link_downloads([section], Path("root"))
    assert len(planned) == 1
    assert planned[0].destination == Path("root/01 - Section 1/Clase 1 - Word Embeddings.pptx")


def test_plan_link_downloads_leaves_opaque_drive_files_without_an_extension() -> None:
    section = _link_section(
        section_num=2,
        name="Zonaprop demo",
        url="https://drive.google.com/file/d/DRIVE1/view?usp=sharing",
    )
    planned = plan_link_downloads([section], Path("root"))
    assert len(planned) == 1
    assert planned[0].destination == Path("root/02 - Section 2/Zonaprop demo")


def test_plan_link_downloads_dedupes_by_url_not_display_name() -> None:
    """Two distinct links can share the module name that becomes the placeholder filename."""
    section = Section(
        id=1,
        name="Section 1",
        section=1,
        modules=[
            Module(
                id=100,
                name="Clase",
                modname="url",
                contents=[
                    CourseFile(
                        filename="Clase",
                        fileurl="https://docs.google.com/presentation/d/DOC1/edit",
                        type="url",
                    )
                ],
            ),
            Module(
                id=101,
                name="Clase",
                modname="url",
                contents=[
                    CourseFile(
                        filename="Clase",
                        fileurl="https://docs.google.com/presentation/d/DOC2/edit",
                        type="url",
                    )
                ],
            ),
        ],
    )
    planned = plan_link_downloads([section], Path("root"))
    destinations = {p.destination for p in planned}
    assert len(planned) == 2
    assert len(destinations) == 2


def test_plan_link_downloads_collapses_the_same_url_repeated() -> None:
    """A duplicated activity pointing at the same doc must not be planned twice."""
    url = "https://docs.google.com/presentation/d/DOC1/edit"
    section = Section(
        id=1,
        name="Section 1",
        section=1,
        modules=[
            Module(
                id=100,
                name="Clase",
                modname="url",
                contents=[CourseFile(filename="Clase", fileurl=url, type="url")],
            ),
            Module(
                id=101,
                name="Clase",
                modname="url",
                contents=[CourseFile(filename="Clase", fileurl=url, type="url")],
            ),
        ],
    )
    planned = plan_link_downloads([section], Path("root"))
    assert len(planned) == 1


def test_plan_link_downloads_filters_by_section() -> None:
    section = _link_section(
        section_num=1, name="Clase", url="https://docs.google.com/presentation/d/DOC1/edit"
    )
    assert plan_link_downloads([section], Path("root"), only_sections={2}) == []


def test_plan_link_downloads_filters_by_module_type() -> None:
    section = _link_section(
        section_num=1, name="Clase", url="https://docs.google.com/presentation/d/DOC1/edit"
    )
    assert plan_link_downloads([section], Path("root"), only_modtypes={"resource"}) == []


# -- fetching links ------------------------------------------------------------------

_SLIDES_EXPORT_URL = "https://docs.google.com/presentation/d/DOC1/export/pptx"
_DRIVE_UC_URL = "https://drive.google.com/uc?export=download&id=DRIVE1"
_DRIVE_CONFIRM_URL = "https://drive.usercontent.google.com/download"


@pytest.fixture
def slides_link() -> CourseFile:
    return CourseFile(
        filename="Clase 1", fileurl="https://docs.google.com/presentation/d/DOC1/edit", type="url"
    )


@pytest.fixture
def drive_link() -> CourseFile:
    return CourseFile(
        filename="Zonaprop demo",
        fileurl="https://drive.google.com/file/d/DRIVE1/view?usp=sharing",
        type="url",
    )


@respx.mock
def test_download_link_writes_a_deterministic_export(
    slides_link: CourseFile, tmp_path: Path
) -> None:
    respx.get(_SLIDES_EXPORT_URL).mock(return_value=httpx.Response(200, content=b"pptx bytes"))
    destination = tmp_path / "Clase 1.pptx"

    with httpx.Client() as http:
        result = download_link(http, slides_link, destination)

    assert result.status is DownloadStatus.DOWNLOADED
    assert destination.read_bytes() == b"pptx bytes"


@respx.mock
def test_download_link_resolves_filename_from_content_disposition(
    drive_link: CourseFile, tmp_path: Path
) -> None:
    respx.get(_DRIVE_UC_URL).mock(
        return_value=httpx.Response(
            200,
            content=b"zip bytes",
            headers={"content-disposition": 'attachment; filename="zonaprop-clase.zip"'},
        )
    )
    placeholder = tmp_path / "Zonaprop demo"

    with httpx.Client() as http:
        result = download_link(http, drive_link, placeholder)

    assert result.path == tmp_path / "zonaprop-clase.zip"
    assert result.path.read_bytes() == b"zip bytes"
    assert not placeholder.exists()


@respx.mock
def test_download_link_falls_back_to_mimetype_when_no_content_disposition(
    drive_link: CourseFile, tmp_path: Path
) -> None:
    respx.get(_DRIVE_UC_URL).mock(
        return_value=httpx.Response(
            200, content=b"%PDF-1.4", headers={"content-type": "application/pdf"}
        )
    )
    placeholder = tmp_path / "Zonaprop demo"

    with httpx.Client() as http:
        result = download_link(http, drive_link, placeholder)

    assert result.path == tmp_path / "Zonaprop demo.pdf"


@respx.mock
def test_download_link_retries_the_virus_scan_interstitial(
    drive_link: CourseFile, tmp_path: Path
) -> None:
    interstitial = (
        b'<form id="download-form" action="https://drive.usercontent.google.com/download">'
        b'<input type="hidden" name="confirm" value="t9k2">'
        b'<input type="hidden" name="uuid" value="abc-uuid">'
        b"</form>"
    )
    respx.get(_DRIVE_UC_URL).mock(
        return_value=httpx.Response(
            200, content=interstitial, headers={"content-type": "text/html"}
        )
    )
    confirm_route = respx.get(_DRIVE_CONFIRM_URL).mock(
        return_value=httpx.Response(200, content=b"zip bytes")
    )
    placeholder = tmp_path / "Zonaprop demo"

    with httpx.Client() as http:
        result = download_link(http, drive_link, placeholder)

    assert result.status is DownloadStatus.DOWNLOADED
    assert result.path.read_bytes() == b"zip bytes"
    retry_params = confirm_route.calls.last.request.url.params
    assert retry_params["confirm"] == "t9k2"
    assert retry_params["uuid"] == "abc-uuid"
    assert retry_params["id"] == "DRIVE1"


@respx.mock
def test_download_link_rejects_a_second_html_response(
    drive_link: CourseFile, tmp_path: Path
) -> None:
    interstitial = (
        b'<form><input type="hidden" name="confirm" value="t9k2">'
        b'<input type="hidden" name="uuid" value="abc-uuid"></form>'
    )
    respx.get(_DRIVE_UC_URL).mock(
        return_value=httpx.Response(
            200, content=interstitial, headers={"content-type": "text/html"}
        )
    )
    respx.get(_DRIVE_CONFIRM_URL).mock(
        return_value=httpx.Response(
            200, content=interstitial, headers={"content-type": "text/html"}
        )
    )

    with httpx.Client() as http, pytest.raises(DownloadError, match="warning page"):
        download_link(http, drive_link, tmp_path / "Zonaprop demo")

    assert list(tmp_path.glob("*.part")) == []


@respx.mock
def test_download_link_rejects_an_empty_response(drive_link: CourseFile, tmp_path: Path) -> None:
    respx.get(_DRIVE_UC_URL).mock(return_value=httpx.Response(200, content=b""))
    destination = tmp_path / "Zonaprop demo"

    with httpx.Client() as http, pytest.raises(DownloadError, match="empty response"):
        download_link(http, drive_link, destination)

    assert not destination.exists()
    assert list(tmp_path.glob("*.part")) == []


def test_download_link_rejects_an_unrecognized_url(tmp_path: Path) -> None:
    github_link = CourseFile(filename="repo", fileurl="https://github.com/example/repo", type="url")
    with httpx.Client() as http, pytest.raises(DownloadError, match="not a downloadable link"):
        download_link(http, github_link, tmp_path / "repo")


@respx.mock
def test_download_link_skips_when_already_present(slides_link: CourseFile, tmp_path: Path) -> None:
    route = respx.get(_SLIDES_EXPORT_URL).mock(return_value=httpx.Response(200, content=b"x"))
    destination = tmp_path / "Clase 1.pptx"
    destination.write_bytes(b"existing")

    with httpx.Client() as http:
        result = download_link(http, slides_link, destination)

    assert result.status is DownloadStatus.SKIPPED
    assert route.call_count == 0


@respx.mock
def test_download_link_skips_an_opaque_drive_file_already_present(
    drive_link: CourseFile, tmp_path: Path
) -> None:
    """An opaque Drive file's real destination isn't known until headers arrive, so the
    skip check runs after that -- not upfront like it does for a known-extension export."""
    route = respx.get(_DRIVE_UC_URL).mock(
        return_value=httpx.Response(
            200,
            content=b"new bytes",
            headers={"content-disposition": 'attachment; filename="zonaprop-clase.zip"'},
        )
    )
    existing = tmp_path / "zonaprop-clase.zip"
    existing.write_bytes(b"already on disk")
    placeholder = tmp_path / "Zonaprop demo"

    with httpx.Client() as http:
        result = download_link(http, drive_link, placeholder)

    assert result.status is DownloadStatus.SKIPPED
    assert result.path == existing
    assert existing.read_bytes() == b"already on disk"
    assert route.call_count == 1
    assert not placeholder.exists()


@respx.mock
def test_download_link_reports_a_native_export_permission_page_distinctly(
    slides_link: CourseFile, tmp_path: Path
) -> None:
    """A Docs/Slides/Sheets permission page is not Drive's virus-scan warning page."""
    respx.get(_SLIDES_EXPORT_URL).mock(
        return_value=httpx.Response(
            200, content=b"<html>request access</html>", headers={"content-type": "text/html"}
        )
    )

    with httpx.Client() as http, pytest.raises(DownloadError, match="HTML page instead"):
        download_link(http, slides_link, tmp_path / "Clase 1.pptx")
