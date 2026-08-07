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

Over MCP, `opens_at` and `closes_at` are full timestamps carrying their offset; the CLI
table prints the date alone, which is the right granularity to scan and the wrong one to
compute a deadline from. See [Deadlines are moments](../README.md#things-worth-knowing).

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
    "opens_at": "2024-02-14T00:00:00-03:00",
    "closes_at": "2024-02-21T23:59:00-03:00",
    "attempt_limit": 2,
    "max_grade": 10.0
  }
]
```

## Show one quiz's status

CLI: `moodle course quiz-status`
MCP: `get_quiz_status`

```
moodle course quiz-status QUIZ_ID [--course COURSE]
```

MCP parameters: `quiz_id`; `course`, optional.

`QUIZ_ID`/`quiz_id` is the id from the listing above, not a course-module id.

Pass the course whenever you know it. Reading the maximum a quiz grades out of means
finding the quiz, and a quiz id alone does not say which course holds it, so without the
hint every enrolled course's quizzes are fetched to locate one. Checking a course's
quizzes one at a time is the ordinary case, and it pulls the whole campus once per quiz.

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
