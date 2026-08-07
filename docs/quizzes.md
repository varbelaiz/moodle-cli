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

**Assignments and quizzes are separate Moodle activity types**, read through entirely
different web-service functions. An "Attempt quiz now" button is a quiz, not an
assignment — it won't appear in the assignments commands, and vice versa.
