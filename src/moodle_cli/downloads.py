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

import httpx

from moodle_cli.errors import DownloadError, MoodleAPIError
from moodle_cli.models import CourseFile, Module, Section

_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WHITESPACE = re.compile(r"\s+")
_JSON_CONTENT_TYPE = "application/json"
_CHUNK = 64 * 1024


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
