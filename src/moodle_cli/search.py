"""Cross-course search over section, activity, file and link names.

The CLI and the MCP server share this so both surfaces answer "which course has X" from
one sweep and hand back the same record shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from moodle_cli.client import MoodleClient
from moodle_cli.models import CourseFile, Module

#: Cap on the hits one search returns. A short substring matches most activity names on a
#: campus, and a flood of records is worth less to the caller than being told to narrow.
RESULT_LIMIT = 50


class MatchKind(StrEnum):
    """Which name the query hit, in the order the search prefers them."""

    SECTION = "section"
    MODULE = "module"
    FILE = "file"
    LINK = "link"


@dataclass(frozen=True, slots=True)
class SearchHit:
    """One match, carrying enough structure to act on it without re-reading the course."""

    course: str
    section: str
    section_number: int
    kind: MatchKind
    module: str | None = None
    module_type: str | None = None
    files: tuple[CourseFile, ...] = ()
    links: tuple[CourseFile, ...] = ()


@dataclass(frozen=True, slots=True)
class SearchResults:
    hits: list[SearchHit]
    truncated: bool

    def as_payload(self) -> dict[str, Any]:
        """Render the JSON both surfaces emit."""
        return {"results": [_hit_payload(hit) for hit in self.hits], "truncated": self.truncated}


def search_contents(
    client: MoodleClient, query: str, *, limit: int = RESULT_LIMIT
) -> SearchResults:
    """Find sections, activities, files and links whose name contains ``query``.

    Matching is a case-insensitive substring of a name, plus a link's destination URL; no
    file content is read. Courses hidden from the dashboard are swept too, so hiding a
    course on the dashboard never hides its material from a search.
    """
    needle = query.casefold().strip()
    if not needle:
        return SearchResults(hits=[], truncated=False)

    hits: list[SearchHit] = []
    for course in client.list_courses(view="all-including-hidden"):
        for section in client.get_course_contents(course.id):
            if needle in section.name.casefold():
                hits.append(
                    SearchHit(
                        course=course.shortname,
                        section=section.name,
                        section_number=section.section,
                        kind=MatchKind.SECTION,
                    )
                )
            for module in section.modules:
                found = _module_hit(needle, module)
                if found is None:
                    continue
                kind, files, links = found
                hits.append(
                    SearchHit(
                        course=course.shortname,
                        section=section.name,
                        section_number=section.section,
                        kind=kind,
                        module=module.name,
                        module_type=module.modname,
                        files=files,
                        links=links,
                    )
                )
        # One hit past the cap already answers "there is more"; the remaining courses would
        # only buy results the caller is being told to narrow away.
        if len(hits) > limit:
            break

    return SearchResults(hits=hits[:limit], truncated=len(hits) > limit)


def _module_hit(
    needle: str, module: Module
) -> tuple[MatchKind, tuple[CourseFile, ...], tuple[CourseFile, ...]] | None:
    """Report a module's match with the file and link lists its kind implies.

    A hit on the module's own name carries its whole contents: filtering them by a needle
    the module name already satisfied would report an empty folder as empty.
    """
    if needle in module.name.casefold():
        return MatchKind.MODULE, tuple(module.files), tuple(module.links)

    files = tuple(f for f in module.files if needle in f.filename.casefold())
    links = tuple(link for link in module.links if _link_matches(needle, link))
    if files:
        return MatchKind.FILE, files, links
    if links:
        return MatchKind.LINK, files, links
    return None


def _link_matches(needle: str, link: CourseFile) -> bool:
    """Search a link's destination as well as its label.

    The service a link points at is often named only in the URL, the label being free text
    a teacher wrote.
    """
    return needle in link.filename.casefold() or needle in (link.fileurl or "").casefold()


def _hit_payload(hit: SearchHit) -> dict[str, Any]:
    """Serialize a hit, keeping module fields off records that describe a section."""
    payload: dict[str, Any] = {
        "course": hit.course,
        "section": hit.section,
        "section_number": hit.section_number,
        "match": hit.kind.value,
    }
    if hit.kind is MatchKind.SECTION:
        return payload
    payload["module"] = hit.module
    payload["type"] = hit.module_type
    payload["files"] = [f.filename for f in hit.files]
    payload["links"] = [{"name": link.filename, "url": link.fileurl} for link in hit.links]
    return payload
