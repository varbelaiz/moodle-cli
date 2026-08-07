# Assignments

## List assignments across every course

CLI: `moodle courses assignments`
MCP: `get_assignments` (no `course` argument)

```
moodle courses assignments [--json]
```

Lists assignments and due dates across every enrolled course, ordered by due date with
undated ones last, so the next deadline is at the top.

## List one course's assignments

CLI: `moodle course assignments`
MCP: `get_assignments` (with `course`)

```
moodle course assignments COURSE [--json]
```

Both commands/the same tool share columns: id, name, due date, and grade (the point
maximum an assignment is worth). The `id` feeds into assignment status below.

Over MCP, `due_at` is a full timestamp carrying its offset; the CLI table prints the date
alone, which is the right granularity to scan and the wrong one to compute a deadline
from. See [Deadlines are moments](../README.md#things-worth-knowing).

**Not every assignment is marked out of points.** Moodle also grades with named scales
("Aprobado", "Insuficiente"); that has no numeric maximum, so the listing reads `scale`
(CLI) or reports `max_grade: null` with `scale_graded: true` (MCP) — the scale's name
itself isn't in this payload. Assignment status, below, shows the awarded value either
way.

**Assignments and quizzes are separate Moodle activity types**, read through entirely
different web-service functions — see [quizzes](quizzes.md).

Example `--json` response — the raw assignment fields:

```json
[
  {
    "id": 4021,
    "cmid": 601,
    "course": 101,
    "name": "Problem Set 1",
    "duedate": 1707868800,
    "allowsubmissionsfromdate": 1706659200,
    "cutoffdate": 0,
    "grade": 100.0
  }
]
```

Example `get_assignments` response — the same assignment, curated: a computed `due_at`
and `max_grade`/`scale_graded` in place of the raw signed `grade`:

```json
[
  {
    "id": 4021,
    "course": "CS101",
    "name": "Problem Set 1",
    "due_at": "2024-02-14T23:59:00-03:00",
    "max_grade": 100.0,
    "scale_graded": false
  }
]
```

## Show one assignment's status

CLI: `moodle course assignment-status`
MCP: `get_assignment_status`

```
moodle course assignment-status ASSIGNMENT_ID
```

MCP parameter: `assignment_id`.

`ASSIGNMENT_ID`/`assignment_id` is the id from the listings above — not a course-module
id, which this call rejects.

Shows submission status, grading status, submitted filenames, and an extension date if
one was granted. The MCP tool returns both `grade` (the raw value to compute with) and
`grade_display` (how the campus renders it) — the latter is the only form that names a
scale grade such as "Aprobado". `extension_due_at` is a full timestamp, for the same
reason `due_at` is one: an extension is a deadline.

Example `--json` response:

```json
{
  "status": "submitted",
  "gradingstatus": "graded",
  "grade": "92.00",
  "gradefordisplay": "92.00",
  "extensionduedate": 0,
  "submitted_files": ["problem_set_1.pdf"]
}
```

Example `get_assignment_status` response — same submission, curated:

```json
{
  "submitted": true,
  "submission_status": "submitted",
  "submitted_files": ["problem_set_1.pdf"],
  "graded": true,
  "grade": "92.00",
  "grade_display": "92.00",
  "extension_due_at": null
}
```
