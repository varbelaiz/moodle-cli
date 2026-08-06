"""Domain models mirroring the Moodle web-service response shapes.

Field selection is deliberate: Moodle returns far more than we need, so every model
ignores unknown keys rather than tracking the full upstream schema.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore")


def _epoch_to_datetime(value: int) -> datetime | None:
    """Moodle uses 0, not null, for unset timestamps."""
    return datetime.fromtimestamp(value, tz=UTC) if value else None


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


class Announcement(_Base):
    """A post in a course's news forum.

    ``courseid`` is not part of the raw discussion payload; ``MoodleClient.get_announcements``
    injects it so callers aggregating across courses can tell posts apart.
    """

    id: int
    courseid: int = 0
    subject: str = ""
    message: str = ""
    userfullname: str = ""
    created: int = 0
    numreplies: int = 0
    pinned: bool = False

    @property
    def posted_at(self) -> datetime | None:
        return _epoch_to_datetime(self.created)

    @property
    def message_text(self) -> str:
        """``message`` with HTML tags stripped; forum posts arrive as HTML."""
        return re.sub(r"<[^>]+>", "", self.message).strip()


class Assignment(_Base):
    id: int
    cmid: int = 0
    course: int = 0
    name: str = ""
    duedate: int = 0
    allowsubmissionsfromdate: int = 0
    cutoffdate: int = 0
    grade: float = 0

    @property
    def due_at(self) -> datetime | None:
        return _epoch_to_datetime(self.duedate)


class AssignmentStatus(_Base):
    """Curated view of ``mod_assign_get_submission_status``.

    The raw response nests submission data under plugin-specific shapes that vary with
    which submission methods (file, online text, ...) the assignment enables. Rather than
    model that whole tree, ``MoodleClient.get_assignment_status`` extracts the fields
    below by hand.
    """

    status: str | None = None
    gradingstatus: str = ""
    grade: str | None = None
    gradefordisplay: str = ""
    extensionduedate: int = 0
    submitted_files: list[str] = Field(default_factory=list)

    @property
    def submitted(self) -> bool:
        return self.status == "submitted"

    @property
    def graded(self) -> bool:
        return self.gradingstatus == "graded"

    @property
    def extension_due_at(self) -> datetime | None:
        return _epoch_to_datetime(self.extensionduedate)


class Quiz(_Base):
    id: int
    coursemodule: int = 0
    course: int = 0
    name: str = ""
    timeopen: int = 0
    timeclose: int = 0
    attempts: int = 0
    grade: float = 0

    @property
    def opens_at(self) -> datetime | None:
        return _epoch_to_datetime(self.timeopen)

    @property
    def closes_at(self) -> datetime | None:
        return _epoch_to_datetime(self.timeclose)


class QuizStatus(_Base):
    """Combines ``mod_quiz_get_user_attempts`` and ``mod_quiz_get_user_best_grade``.

    Neither call alone answers "did I take this and how did it go" — attempts carries no
    grade, and the best-grade call carries no attempt history.
    """

    attempt_count: int = 0
    last_state: str | None = None
    has_grade: bool = False
    grade: float | None = None
    grade_to_pass: float | None = None


class CourseGrade(_Base):
    courseid: int
    grade: str = ""
    rank: str | None = None


class GradeItem(_Base):
    """A row in a course's per-item grade breakdown.

    A category subtotal row carries no ``itemname`` and no ``itemmodule`` — both arrive
    ``null`` rather than absent or empty.
    """

    itemname: str | None = None
    itemmodule: str | None = None
    graderaw: float | None = None
    grademax: float = 0
    gradeformatted: str = ""
    percentageformatted: str = ""
    feedback: str = ""


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
