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

## Review a finished attempt

CLI: `moodle course quiz-review`
MCP: `get_quiz_review`

```
moodle course quiz-review QUIZ_ID [--attempt N] [--json]
```

MCP parameters: `quiz_id`; `attempt`, optional.

Shows what a finished attempt asked: each question's prompt, the options offered, your
answer with a per-part verdict, the right answer and the feedback. A choice that has
feedback of its own carries it on its answer, apart from the question's feedback. `--attempt` takes the
attempt number from 1 and defaults to the latest finished attempt.

Every question type the campus uses is read into the same shape: true/false and multiple
choice (one answer per option chosen), short answer (the text typed), matching (one
`stem -> choice` answer per row), and the two fill-the-gaps types, drop-down and drag and
drop (the prompt reads with each gap filled in as `[choice]`, one answer per gap).

**The quiz decides what you may see.** Each quiz sets review options for whether an
answer was right, the right answer and the feedback, and the campus leaves a withheld part
out of the page entirely. Such a part comes back as `null` and is left out of the CLI
output; it is never reported as an empty answer. A quiz that allows no review at all is
an error (`noreview`), not an empty review.

`marks` is the attempt's raw score out of `max_marks`, the sum of each question's
`max_mark`; it is not rescaled to the quiz's grade the way `quiz-status` reports it.

Example `--json` response, and the `get_quiz_review` response alike:

```json
{
  "quiz_id": 3305,
  "attempt_id": 90211,
  "attempt": 1,
  "marks": 1.0,
  "timefinish": 1708473000,
  "questions": [
    {
      "number": "1",
      "type": "truefalse",
      "state": "gradedright",
      "mark": 1.0,
      "max_mark": 1.0,
      "prompt": "Is a for loop guaranteed to run at least once?",
      "choices": ["True", "False"],
      "answers": [{"text": "False", "correct": true, "feedback": null}],
      "right_answer": "The correct answer is 'False'.",
      "feedback": null,
      "general_feedback": "A do-while loop is the one that always runs once."
    }
  ],
  "max_marks": 1.0
}
```

## Export every quiz of a course

CLI: `moodle course quiz-export`

```
moodle course quiz-export COURSE [-o DIR]
```

Writes the latest finished attempt of each quiz in the course as one markdown file, the
same text `quiz-review` prints, under `./<shortname>/Quizzes/` by default. A quiz with no
finished attempt, or one that allows no review, is listed as skipped with the reason
rather than dropped. Two quizzes sharing a name get the quiz id appended so neither
overwrites the other.

**Assignments and quizzes are separate Moodle activity types**, read through entirely
different web-service functions. An "Attempt quiz now" button is a quiz, not an
assignment — it won't appear in the assignments commands, and vice versa.
