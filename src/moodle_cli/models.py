"""Domain models mirroring the Moodle web-service response shapes.

Field selection is deliberate: Moodle returns far more than we need, so every model
ignores unknown keys rather than tracking the full upstream schema.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from html import unescape

from pydantic import BaseModel, ConfigDict, Field


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore")


def _epoch_to_datetime(value: int) -> datetime | None:
    """Moodle uses 0, not null, for unset timestamps."""
    return datetime.fromtimestamp(value, tz=UTC) if value else None


#: Tags that end a line of prose. Everything else is stripped without a separator.
_BLOCK_TAG = re.compile(
    r"</?(?:br|p|div|li|ul|ol|tr|table|h[1-6]|blockquote)\b[^>]*>", re.IGNORECASE
)
_ANY_TAG = re.compile(r"<[^>]+>")


def html_to_text(markup: str) -> str:
    """Plain text from a Moodle HTML fragment, one line per block element.

    Moodle stores authored prose as HTML. Dropping tags without putting a separator in
    their place runs the last word of a block into the first word of the next, and an
    entity left encoded reaches the reader as ``&nbsp;``.
    """
    stripped = _ANY_TAG.sub("", _BLOCK_TAG.sub("\n", markup))
    lines = (" ".join(line.split()) for line in unescape(stripped).split("\n"))
    return "\n".join(line for line in lines if line)


class Course(_Base):
    id: int
    shortname: str
    fullname: str
    category: str = Field(default="", alias="coursecategory")
    startdate: int = 0
    enddate: int = 0
    isfavourite: bool = False
    hidden: bool = False
    progress: float | None = None
    viewurl: str = ""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    @property
    def started_at(self) -> datetime | None:
        return _epoch_to_datetime(self.startdate)

    @property
    def ended_at(self) -> datetime | None:
        """None on this campus: course end dates are never configured."""
        return _epoch_to_datetime(self.enddate)


class CourseFile(_Base):
    """A file entry inside a module's ``contents``.

    Several of these fields arrive as ``null`` rather than absent (``filepath`` on url
    modules, for one), so they are optional rather than defaulted strings.
    """

    filename: str
    filepath: str | None = None
    filesize: int = 0
    fileurl: str | None = None
    mimetype: str | None = None
    timemodified: int = 0
    type: str | None = None
    isexternalfile: bool = False

    @property
    def is_downloadable(self) -> bool:
        """Whether this entry is a real file rather than a link.

        ``url`` modules carry entries with ``type == "url"`` that point at external sites.
        ``isexternalfile`` is deliberately *not* excluded: it marks a file stored in an
        external repository, which Moodle still serves through ``pluginfile.php`` (the
        course bibliography folders are all flagged this way).
        """
        return self.type == "file" and bool(self.fileurl)


class Module(_Base):
    id: int
    name: str
    modname: str
    url: str | None = None
    visible: bool = True
    uservisible: bool = True
    contents: list[CourseFile] = Field(default_factory=list)

    @property
    def files(self) -> list[CourseFile]:
        return [c for c in self.contents if c.is_downloadable]

    @property
    def links(self) -> list[CourseFile]:
        """External link entries, e.g. a ``url``-type module's actual target.

        These carry no bytes to download, but the destination itself is real information
        that ``files`` deliberately excludes.
        """
        return [c for c in self.contents if c.type == "url" and c.fileurl]


class Section(_Base):
    id: int
    name: str
    section: int = 0
    visible: bool = True
    uservisible: bool = True
    summary: str = ""
    modules: list[Module] = Field(default_factory=list)


class Role(_Base):
    roleid: int = 0
    name: str = ""
    shortname: str = ""


class Participant(_Base):
    id: int
    fullname: str
    firstname: str = ""
    lastname: str = ""
    email: str | None = None
    roles: list[Role] = Field(default_factory=list)
    lastcourseaccess: int = 0

    @property
    def role_names(self) -> list[str]:
        return [r.shortname for r in self.roles]

    @property
    def last_course_access(self) -> datetime | None:
        return _epoch_to_datetime(self.lastcourseaccess)


class SiteInfo(_Base):
    sitename: str = ""
    username: str = ""
    fullname: str = ""
    userid: int = 0
    release: str = ""
    downloadfiles: bool = False
    functions: list[dict[str, object]] = Field(default_factory=list)

    @property
    def function_names(self) -> set[str]:
        return {str(f["name"]) for f in self.functions if "name" in f}
