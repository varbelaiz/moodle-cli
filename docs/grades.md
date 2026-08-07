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

Example response — identical shape for `--json` and `get_grade_summary`:

```json
[
  {"course": "CS101", "grade": "87.30"}
]
```

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

Example `--json` response — the raw grade-item fields, an activity row followed by the
unnamed course-total row:

```json
[
  {
    "itemname": "Problem Set 1",
    "itemtype": "mod",
    "itemmodule": "assign",
    "graderaw": 92.0,
    "grademax": 100.0,
    "gradeformatted": "92.00",
    "percentageformatted": "92.00 %",
    "feedback": "Nice work overall."
  },
  {
    "itemname": null,
    "itemtype": "course",
    "itemmodule": null,
    "graderaw": 87.3,
    "grademax": 100.0,
    "gradeformatted": "87.30",
    "percentageformatted": "87.30 %",
    "feedback": ""
  }
]
```

Example `get_grades` response — the same two rows, curated: `item` names the unnamed
total row "Course total" instead of leaving it `null`.

```json
[
  {
    "item": "Problem Set 1",
    "grade": "92.00",
    "max": 100.0,
    "percentage": "92.00 %",
    "feedback": "Nice work overall."
  },
  {
    "item": "Course total",
    "grade": "87.30",
    "max": 100.0,
    "percentage": "87.30 %",
    "feedback": ""
  }
]
```
