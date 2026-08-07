# Grades

## Grade summary across every course

CLI: `moodle courses grades`
MCP: `get_grade_summary`

```
moodle courses grades [--json]
```

Shows a course-level grade summary across every enrolled course. Only courses with a
course-level grade appear. This works even for a course whose instructor hasn't opened
the gradebook to students — see the per-item breakdown below for that detail.

## Per-item breakdown for one course

CLI: `moodle course grades`
MCP: `get_grades`

```
moodle course grades COURSE [--json]
```

MCP parameter: `course`, required.

Shows the per-item grade breakdown for one course — assignments, quizzes, and the course
total. Moodle sends the course total and any category subtotal without a name; those rows
are labelled by their type (e.g. "Course total").

**Per-item grades depend on the instructor, not on you.** This fails with a clear error if
the instructor hasn't opened the gradebook to students in this course; the cross-course
summary above still works in that case, just without the per-item detail.
