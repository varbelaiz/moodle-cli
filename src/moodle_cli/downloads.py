"""File downloads.

``pluginfile.php`` answers an unauthenticated or malformed request with HTTP 200 and a JSON
error body. Written straight to disk that becomes a 141-byte file named ``Programa.pdf`` that
looks like a successful download, so every transfer is validated against the content type and
the ``filesize`` the API already told us to expect.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Collection, Iterator
from dataclasses import dataclass
from enum import StrEnum
from fnmatch import fnmatch
from pathlib import Path
from urllib.parse import urlparse

import httpx

from moodle_cli.errors import DownloadError, MoodleAPIError
from moodle_cli.models import CourseFile, Module, Section

_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WHITESPACE = re.compile(r"\s+")
_JSON_CONTENT_TYPE = "application/json"
_HTML_CONTENT_TYPE = "text/html"
_CHUNK = 64 * 1024

# Google's stable, documented export API: the URL path segment right after
# docs.google.com/ names the document type, and each type has exactly one export format
# this app asks for -- native, not PDF, since that's what re-editing and `anydoc` want.
_GOOGLE_DOC_EXTENSIONS = {"presentation": "pptx", "document": "docx", "spreadsheets": "xlsx"}
_DOC_ID = re.compile(r"/d/([\w-]+)")
_COLAB_ID = re.compile(r"/drive/([\w-]+)")
_DRIVE_EXPORT_URL = "https://drive.google.com/uc?export=download&id={id}"
_DRIVE_CONFIRM_URL = "https://drive.usercontent.google.com/download"
_CONFIRM_TOKEN = re.compile(r'name="confirm"\s+value="([^"]+)"')
_CONFIRM_UUID = re.compile(r'name="uuid"\s+value="([^"]+)"')
_CONTENT_DISPOSITION_FILENAME = re.compile(r'filename="([^"]+)"')
_MIME_EXTENSIONS = {
    "application/pdf": "pdf",
    "application/zip": "zip",
    "application/x-zip-compressed": "zip",
    "application/json": "ipynb",  # a Colab notebook served without a Content-Disposition
    "video/mp4": "mp4",
    "image/png": "png",
    "image/jpeg": "jpg",
}


class DownloadStatus(StrEnum):
    DOWNLOADED = "downloaded"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class PlannedDownload:
    """A file to fetch, paired with the destination its course structure implies."""

    file: CourseFile
    section: Section
    module: Module
    destination: Path


@dataclass(frozen=True)
class DownloadResult:
    path: Path
    status: DownloadStatus
    size: int


@dataclass(frozen=True)
class PlannedLink:
    """A Google-hosted course link to fetch, paired with the destination its course
    structure implies.

    Unlike `PlannedDownload`, `destination` may be missing its extension: an opaque
    Drive file's real name isn't known until `download_link` reads the response.
    """

    link: CourseFile
    section: Section
    module: Module
    destination: Path


@dataclass(frozen=True)
class _GoogleExport:
    """Where to fetch a Google-hosted link, and whether its extension is already known.

    `drive_id` is set only for opaque Drive files -- it's what a virus-scan-warning
    confirm-token retry needs, and native Docs/Slides/Sheets exports never hit that gate.
    """

    export_url: str
    extension: str | None
    drive_id: str | None = None


def sanitize(name: str, *, fallback: str = "untitled") -> str:
    """Make a path component safe without mangling accented course names."""
    cleaned = unicodedata.normalize("NFC", name)
    cleaned = _UNSAFE.sub("-", cleaned)
    cleaned = _WHITESPACE.sub(" ", cleaned).strip(" .")
    return cleaned or fallback


def dedupe_extension(filename: str) -> str:
    """Collapse a doubled extension: ``Programa.pdf.pdf`` -> ``Programa.pdf``.

    Course material is routinely uploaded with the extension typed twice.
    """
    stem = Path(filename)
    if stem.suffix and stem.stem.endswith(stem.suffix):
        return stem.stem
    return filename


def iter_course_files(sections: list[Section]) -> Iterator[tuple[Section, Module, CourseFile]]:
    for section in sections:
        for module in section.modules:
            for file in module.files:
                yield section, module, file


def iter_course_links(sections: list[Section]) -> Iterator[tuple[Section, Module, CourseFile]]:
    for section in sections:
        for module in section.modules:
            for link in module.links:
                yield section, module, link


def _classify_google_url(url: str) -> _GoogleExport | None:
    """Map a course link to how to fetch it, or None if it isn't a recognized Google host.

    GitHub, Slack, YouTube and similar links have nothing this app can export -- they stay
    listed-only, same as before this existed.
    """
    parsed = urlparse(url)
    host = parsed.hostname or ""

    if host == "docs.google.com":
        parts = parsed.path.strip("/").split("/")
        if len(parts) < 3 or parts[0] not in _GOOGLE_DOC_EXTENSIONS or parts[1] != "d":
            return None
        doc_id, extension = parts[2], _GOOGLE_DOC_EXTENSIONS[parts[0]]
        export_url = (
            f"https://docs.google.com/presentation/d/{doc_id}/export/{extension}"
            if parts[0] == "presentation"
            else f"https://docs.google.com/{parts[0]}/d/{doc_id}/export?format={extension}"
        )
        return _GoogleExport(export_url=export_url, extension=extension)

    if host == "drive.google.com":
        match = _DOC_ID.search(parsed.path)
        if not match:
            return None
        drive_id = match.group(1)
        return _GoogleExport(
            export_url=_DRIVE_EXPORT_URL.format(id=drive_id), extension=None, drive_id=drive_id
        )

    if host == "colab.research.google.com":
        match = _COLAB_ID.search(parsed.path)
        if not match:
            return None
        drive_id = match.group(1)
        return _GoogleExport(
            export_url=_DRIVE_EXPORT_URL.format(id=drive_id), extension=None, drive_id=drive_id
        )

    return None


def matches_selection(
    filename: str,
    names: Collection[str] | None,
    patterns: Collection[str] | None,
) -> bool:
    """Whether a file is picked by the name/pattern selectors.

    Names match exactly, so a value copied out of `course contents` selects precisely that
    file. Patterns are case-insensitive globs. With both given the selection is their union;
    with neither, everything passes.
    """
    if names is None and patterns is None:
        return True
    if names and filename in names:
        return True
    return bool(patterns) and any(
        fnmatch(filename.casefold(), p.casefold()) for p in patterns or ()
    )


def plan_downloads(
    sections: list[Section],
    root: Path,
    *,
    only_sections: set[int] | None = None,
    only_modtypes: set[str] | None = None,
    only_names: Collection[str] | None = None,
    only_patterns: Collection[str] | None = None,
) -> list[PlannedDownload]:
    """Map course contents onto destination paths.

    Sections become directories. A Moodle ``folder`` module becomes a nested directory,
    which both matches how it reads on the course page and keeps identically named files
    from different modules out of each other's way.

    Section and module-type filters compose with the name selectors by intersection.
    """
    planned: list[PlannedDownload] = []
    claimed: dict[Path, int] = {}

    for section, module, file in iter_course_files(sections):
        if only_sections is not None and section.section not in only_sections:
            continue
        if only_modtypes is not None and module.modname not in only_modtypes:
            continue
        if not matches_selection(file.filename, only_names, only_patterns):
            continue

        parts = [sanitize(f"{section.section:02d} - {section.name}", fallback="section")]
        if module.modname == "folder":
            parts.append(sanitize(module.name, fallback="folder"))
        inner = (file.filepath or "").strip("/")
        parts.extend(sanitize(p) for p in inner.split("/") if p)

        filename = sanitize(dedupe_extension(file.filename), fallback="file")
        destination = _claim(root.joinpath(*parts, filename), file.filesize, module.id, claimed)
        if destination is None:
            continue

        planned.append(
            PlannedDownload(
                file=file,
                section=section,
                module=module,
                destination=destination,
            )
        )
    return planned


def _claim(
    destination: Path, filesize: int, module_id: int, claimed: dict[Path, int]
) -> Path | None:
    """Resolve a destination against the paths already claimed by this plan.

    Two activities in one section can point at the same filename. Teachers duplicate
    activities, so the usual case is byte-identical copies, which collapse to one file.
    When the sizes differ they are genuinely different documents, and the second is renamed
    rather than allowed to overwrite the first. Returns None when the entry is a duplicate.
    """
    candidate = destination
    suffix = 0
    while True:
        existing = claimed.get(candidate)
        if existing is None:
            claimed[candidate] = filesize
            return candidate
        if existing == filesize:
            return None
        suffix += 1
        stem = (
            f"{destination.stem} ({module_id})"
            if suffix == 1
            else (f"{destination.stem} ({module_id}-{suffix})")
        )
        candidate = destination.with_name(f"{stem}{destination.suffix}")


def plan_link_downloads(
    sections: list[Section],
    root: Path,
    *,
    only_sections: set[int] | None = None,
    only_modtypes: set[str] | None = None,
) -> list[PlannedLink]:
    """Map course links onto destination paths, mirroring `plan_downloads`' directory layout.

    Only Google-hosted links are planned; `_classify_google_url` returning None for
    everything else (GitHub, Slack, YouTube, ...) is the skip signal, not an error.
    """
    planned: list[PlannedLink] = []
    claimed: dict[Path, str] = {}

    for section, module, link in iter_course_links(sections):
        if only_sections is not None and section.section not in only_sections:
            continue
        if only_modtypes is not None and module.modname not in only_modtypes:
            continue
        export = _classify_google_url(link.fileurl or "")
        if export is None:
            continue

        parts = [sanitize(f"{section.section:02d} - {section.name}", fallback="section")]
        if module.modname == "folder":
            parts.append(sanitize(module.name, fallback="folder"))

        stem = sanitize(link.filename, fallback="link")
        filename = f"{stem}.{export.extension}" if export.extension else stem
        destination = _claim_link(
            root.joinpath(*parts, filename), export.export_url, module.id, claimed
        )
        if destination is None:
            continue

        planned.append(
            PlannedLink(link=link, section=section, module=module, destination=destination)
        )
    return planned


def _claim_link(
    destination: Path, export_url: str, module_id: int, claimed: dict[Path, str]
) -> Path | None:
    """Resolve a link's destination against the links already claimed by this plan.

    Every link's `filesize` is 0, so `_claim`'s byte-identity check can't tell two
    activities with the same display name apart -- the resolved export URL is the
    identity here instead. Returns None when the entry is a duplicate.
    """
    candidate = destination
    suffix = 0
    while True:
        existing = claimed.get(candidate)
        if existing is None:
            claimed[candidate] = export_url
            return candidate
        if existing == export_url:
            return None
        suffix += 1
        stem = (
            f"{destination.stem} ({module_id})"
            if suffix == 1
            else (f"{destination.stem} ({module_id}-{suffix})")
        )
        candidate = destination.with_name(f"{stem}{destination.suffix}")


def download_file(
    http: httpx.Client,
    file: CourseFile,
    token: str,
    destination: Path,
    *,
    overwrite: bool = False,
) -> DownloadResult:
    """Fetch one file, validating that what arrived is actually the file."""
    if not file.fileurl:
        raise DownloadError(f"{file.filename}: no download URL")

    if not overwrite and destination.exists():
        existing = destination.stat().st_size
        if file.filesize == 0 or existing == file.filesize:
            return DownloadResult(path=destination, status=DownloadStatus.SKIPPED, size=existing)

    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")

    try:
        with http.stream("GET", file.fileurl, params={"token": token}) as response:
            response.raise_for_status()
            _reject_error_payload(response, file)

            written = 0
            with partial.open("wb") as handle:
                for chunk in response.iter_bytes(_CHUNK):
                    handle.write(chunk)
                    written += len(chunk)

        if file.filesize and written != file.filesize:
            raise DownloadError(
                f"{file.filename}: expected {file.filesize} bytes, received {written}"
            )
    except BaseException:
        partial.unlink(missing_ok=True)
        raise

    partial.replace(destination)
    return DownloadResult(path=destination, status=DownloadStatus.DOWNLOADED, size=written)


def _reject_error_payload(response: httpx.Response, file: CourseFile) -> None:
    """Turn a 200-with-JSON-error into an exception before anything reaches disk."""
    content_type = response.headers.get("content-type", "")
    if _JSON_CONTENT_TYPE not in content_type:
        return
    if file.mimetype and _JSON_CONTENT_TYPE in file.mimetype:
        return  # the file itself really is JSON

    response.read()
    try:
        payload = response.json()
    except (ValueError, json.JSONDecodeError):
        raise DownloadError(f"{file.filename}: server returned JSON instead of the file") from None

    raise MoodleAPIError(
        errorcode=str(payload.get("errorcode", "unknown")),
        message=str(payload.get("error") or payload.get("message") or "Download failed"),
        function=f"download:{file.filename}",
    )


def download_link(
    http: httpx.Client,
    link: CourseFile,
    destination: Path,
    *,
    overwrite: bool = False,
) -> DownloadResult:
    """Fetch a Google-hosted course link, resolving its real filename if the URL doesn't carry one.

    Large Drive files come back as an HTML "can't scan this file for viruses" page instead
    of the file; that page is retried once with a confirm token scraped out of it. A second
    HTML response is not retried further -- this is screen-scraping an undocumented Google
    page, not a stable API, so it must fail loudly rather than write that page to disk as
    though it were the file.

    Unlike ``pluginfile.php``, Google does answer with real HTTP error statuses: an export
    can 401/403 when the doc isn't actually shared "anyone with the link" despite Moodle
    linking it, or a Drive file's redirect chain can land on an accounts.google.com sign-in
    page for the same reason (still 200, but no confirm token to find). Both are reported as
    a `DownloadError` naming the cause, not left to `httpx`'s generic status exception, which
    the caller doesn't catch and would otherwise abort every other planned download too.
    """
    export = _classify_google_url(link.fileurl or "")
    if export is None:
        raise DownloadError(f"{link.filename}: not a downloadable link")

    if not overwrite and export.extension and destination.exists() and destination.stat().st_size:
        return DownloadResult(
            path=destination, status=DownloadStatus.SKIPPED, size=destination.stat().st_size
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    request_url, params = export.export_url, None

    for attempt in range(2):
        with http.stream("GET", request_url, params=params) as response:
            if response.is_error:
                hint = (
                    ' -- the doc likely is not shared "anyone with the link"'
                    if response.status_code in (401, 403)
                    else ""
                )
                raise DownloadError(
                    f"{link.filename}: Google returned HTTP {response.status_code}{hint}"
                )

            if _HTML_CONTENT_TYPE in response.headers.get("content-type", ""):
                response.read()
                if response.url.host == "accounts.google.com":
                    raise DownloadError(
                        f"{link.filename}: Drive redirected to a Google sign-in page "
                        '-- the file likely is not shared "anyone with the link"'
                    )
                if attempt or export.drive_id is None:
                    raise DownloadError(
                        f"{link.filename}: Drive served a warning page instead of the file"
                    )
                request_url, params = _confirm_retry(export.drive_id, response.text, link)
                continue

            final = _resolve_link_filename(destination, export, response)
            return _write_link_to_disk(response, final, link)

    raise DownloadError(f"{link.filename}: Drive served a warning page instead of the file")


def _confirm_retry(
    drive_id: str, interstitial_html: str, link: CourseFile
) -> tuple[str, dict[str, str]]:
    """Pull the confirm token and uuid Drive's virus-scan warning page needs for a retry."""
    confirm = _CONFIRM_TOKEN.search(interstitial_html)
    uuid = _CONFIRM_UUID.search(interstitial_html)
    if not confirm or not uuid:
        raise DownloadError(
            f"{link.filename}: could not find a confirm token on Drive's warning page"
        )
    params = {
        "id": drive_id,
        "export": "download",
        "confirm": confirm.group(1),
        "uuid": uuid.group(1),
    }
    return _DRIVE_CONFIRM_URL, params


def _resolve_link_filename(
    destination: Path, export: _GoogleExport, response: httpx.Response
) -> Path:
    """Rename an opaque Drive file's placeholder destination once its real name is known."""
    if export.extension:
        return destination

    disposition = response.headers.get("content-disposition", "")
    match = _CONTENT_DISPOSITION_FILENAME.search(disposition)
    if match:
        name = sanitize(dedupe_extension(match.group(1)), fallback=destination.name)
        return destination.with_name(name)

    content_type = response.headers.get("content-type", "").split(";")[0].strip()
    extension = _MIME_EXTENSIONS.get(content_type)
    return destination.with_name(f"{destination.name}.{extension}") if extension else destination


def _write_link_to_disk(
    response: httpx.Response, destination: Path, link: CourseFile
) -> DownloadResult:
    partial = destination.with_name(destination.name + ".part")
    try:
        written = 0
        with partial.open("wb") as handle:
            for chunk in response.iter_bytes(_CHUNK):
                handle.write(chunk)
                written += len(chunk)

        if written == 0:
            raise DownloadError(f"{link.filename}: Drive returned an empty response")
    except BaseException:
        partial.unlink(missing_ok=True)
        raise

    partial.replace(destination)
    return DownloadResult(path=destination, status=DownloadStatus.DOWNLOADED, size=written)
