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

**Not every assignment is marked out of points.** Moodle also grades with named scales
("Aprobado", "Insuficiente"); that has no numeric maximum, so the listing reads `scale`
(CLI) or reports `max_grade: null` with `scale_graded: true` (MCP) — the scale's name
itself isn't in this payload. Assignment status, below, shows the awarded value either
way.

**Assignments and quizzes are separate Moodle activity types**, read through entirely
different web-service functions — see [quizzes](quizzes.md).

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
scale grade such as "Aprobado".
