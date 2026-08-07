# Quizzes

## List a course's quizzes

CLI: `moodle course quizzes`
MCP: `get_quizzes`

```
moodle course quizzes COURSE [--json]
```

MCP parameter: `course`, optional — omit it to check every enrolled course.

Lists a course's quizzes and their open/close windows, attempt limit and max grade.
`attempts` (CLI) / `attempt_limit` (MCP) is unlimited when the quiz sets no cap — shown as
`unlimited` on the CLI and `null` over MCP.

The `id` column/field feeds into quiz status below.

Example `--json` response — the raw quiz fields:

```json
[
  {
    "id": 3305,
    "course": 101,
    "name": "Quiz 1: Variables and Loops",
    "timeopen": 1707868800,
    "timeclose": 1708473600,
    "attempts": 2,
    "grade": 10.0
  }
]
```

Example `get_quizzes` response — the same quiz, curated: `opens_at`/`closes_at` as dates
and `attempt_limit` in place of the raw `attempts`:

```json
[
  {
    "id": 3305,
    "course": "CS101",
    "name": "Quiz 1: Variables and Loops",
    "opens_at": "2024-02-14",
    "closes_at": "2024-02-21",
    "attempt_limit": 2,
    "max_grade": 10.0
  }
]
```

## Show one quiz's status

CLI: `moodle course quiz-status`
MCP: `get_quiz_status`

```
moodle course quiz-status QUIZ_ID
```

MCP parameter: `quiz_id`.

`QUIZ_ID`/`quiz_id` is the id from the listing above, not a course-module id.

Shows attempt count and best grade for one quiz. The grade is scaled to the quiz maximum,
which is why it's always printed alongside it. When no grade can be read, the response
says so without claiming the quiz is ungraded: the same flag covers an unattempted quiz,
one awaiting manual grading, and one whose marks the instructor hides.

Example `--json` response:

```json
{
  "attempt_count": 1,
  "last_state": "finished",
  "has_grade": true,
  "grade": 8.5,
  "grade_to_pass": 5.0,
  "max_grade": 10.0
}
```

Example `get_quiz_status` response — same attempt, renamed fields:

```json
{
  "attempts_used": 1,
  "last_attempt_state": "finished",
  "grade_available": true,
  "grade": 8.5,
  "grade_to_pass": 5.0,
  "max_grade": 10.0
}
```

**Assignments and quizzes are separate Moodle activity types**, read through entirely
different web-service functions. An "Attempt quiz now" button is a quiz, not an
assignment — it won't appear in the assignments commands, and vice versa.
