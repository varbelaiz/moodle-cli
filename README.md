# moodle-cli

Command line client and MCP server for a Moodle campus. Lists your courses, reads their
contents and announcements, downloads the material, shows who is enrolled, and tracks
assignments, quizzes and grades — over Moodle's web-service API, with no browser and no
HTML scraping.

Works with any Moodle instance that has web services and the mobile service enabled.

- [Install](#install)
- [Authentication](#authentication)
- [Command reference](#command-reference)
  - [`moodle auth`](#moodle-auth)
  - [`moodle courses list`](#moodle-courses-list)
  - [`moodle courses grades`](#moodle-courses-grades)
  - [`moodle course contents`](#moodle-course-contents)
  - [`moodle course download`](#moodle-course-download)
  - [`moodle course participants`](#moodle-course-participants)
  - [`moodle course announcements`](#moodle-course-announcements)
  - [`moodle course assignments`](#moodle-course-assignments)
  - [`moodle course assignment-status`](#moodle-course-assignment-status)
  - [`moodle course quizzes`](#moodle-course-quizzes)
  - [`moodle course quiz-status`](#moodle-course-quiz-status)
  - [`moodle course grades`](#moodle-course-grades)
- [MCP server](#mcp-server)
- [Configuration](#configuration)
- [Exit codes](#exit-codes)
- [Things worth knowing](#things-worth-knowing)
- [Development](#development)

## Install

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/varbelaiz/moodle-cli
cd moodle-cli
uv sync
```

Commands below are written as `moodle …`. Without installing the package on your PATH,
prefix them with `uv run`, as in `uv run moodle courses list`.

## Authentication

Point the tool at your campus and log in once:

```bash
export MOODLE_URL=https://campus.example.edu
moodle auth login
```

`auth login` exchanges your password for a long-lived web-service token and stores it in
the system keyring. The password is prompted for, never taken as an argument, and is not
needed again afterwards.

If your campus uses SSO only and you have no local Moodle password, `login/token.php`
cannot mint a token for you. Where the site allows it, you can create one by hand under
Preferences → Security keys in your Moodle profile, then set `MOODLE_TOKEN`.

## Command reference

Every read command accepts `--json`, which prints machine-readable output instead of a
table.

Commands that take a course accept either its numeric id or a shortname prefix:
`moodle course contents 29272` and `moodle course contents IOS460` are equivalent. A prefix
matching more than one course is an error listing the candidates.

### `moodle auth`

| Command | Description |
| --- | --- |
| `moodle auth login [-u USERNAME]` | Mint a token and store it in the keyring. Prompts for the password. |
| `moodle auth status` | Show who the stored token belongs to, and what it can do. |
| `moodle auth logout` | Delete the stored token. |

```console
$ moodle auth status
Authenticated as Ada Lovelace (id 63643)
  site: Universidad de Ejemplo - Campus Virtual
  functions available: 439
  file downloads allowed: True
```

### `moodle courses list`

Lists your enrolled courses.

| Option | Values | Default | Description |
| --- | --- | --- | --- |
| `--view` | `all`, `all-including-hidden`, `in-progress`, `future`, `past`, `starred`, `hidden` | `all` | Which courses to include. |
| `--sort` | `name`, `last-accessed` | `name` | Ordering. |
| `--json` | | | JSON output. |

```console
$ moodle courses list --view starred --sort last-accessed
                       5 courses (starred, by last-accessed)
┏━━━━━━━┳━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━┳━━━┓
┃    id ┃ shortname       ┃ name                                      ┃ year ┃ * ┃
┡━━━━━━━╇━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━╇━━━┩
│ 29272 │ IOS460 - 123246 │ Taller de Desarrollo de Software (grupo…  │ 2026 │ * │
│ 29273 │ IOS465 - 123247 │ Computación cuántica (grupo 1) G:1 Teó 1  │ 2026 │ * │
└───────┴─────────────────┴───────────────────────────────────────────┴──────┴───┘
```

The `--json` output carries more fields than the table, including `category`, `startdate`,
`enddate`, `progress`, `hidden` and `viewurl`.

### `moodle courses grades`

Shows a course-level grade summary across every enrolled course.

```console
$ moodle courses grades
Grade summary (1 courses)
┏━━━━━━━━━━━━━━━┳━━━━━━━┓
┃ course        ┃ grade ┃
┡━━━━━━━━━━━━━━━╇━━━━━━━┩
│ I204 - 101313 │ 51.50 │
└───────────────┴───────┘
```

Only courses with a course-level grade appear. This works even for a course whose
instructor has not opened the gradebook to students — use
[`moodle course grades`](#moodle-course-grades) for the per-item breakdown of one course,
which does require that.

### `moodle course contents`

Shows a course's sections, activities, downloadable files and external links.

```console
$ moodle course contents IOS460
IOS460 - 123246 — Taller de Desarrollo de Software

 0. General  (4 files)
     forum      Avisos
     resource   Programa de la materia
        167.8 KB  Programa - Taller de Desarrollo de Software.pdf
     folder     Material Bibliográfico Digital
        840.6 KB  _Carátula licencia.pdf
         28.0 MB  Bass, L. Software Architecture in Practice.pdf
     lti        Clases Grabadas

15. Importante acceder  (2 links)
     url        Slack de la Materia
            link  https://join.slack.com/t/udesa-tds/shared_invite/...
     url        Organización de GitHub de la materia
            link  https://github.com/tds-udesa
```

Activities without downloadable files — forums, quizzes, assignments — are listed without
file entries. A `url` module (an external link, e.g. a recorded-class or third-party site)
shows its actual destination as a `link` line instead: nothing follows it, it is
informational only. Filenames printed here can be passed verbatim to `course download
--file`.

### `moodle course download`

Downloads a course's files into `./<shortname>/`, mirroring its section structure. Moodle
folders become nested directories.

| Option | Description |
| --- | --- |
| `--output`, `-o PATH` | Destination directory. Default `./<shortname>/`. |
| `--section N` | Only this section number. Repeatable. |
| `--type TYPE` | Only these module types, e.g. `resource`, `folder`. Repeatable. |
| `--file NAME` | Exact filename as printed by `course contents`. Repeatable. |
| `--match GLOB` | Case-insensitive glob on the filename, e.g. `'*.pdf'`. Repeatable. |
| `--dry-run` | List what would be downloaded and write nothing. |
| `--overwrite` | Re-download files that already exist. |

`--section` and `--type` narrow by structure, `--file` and `--match` by filename. All four
compose by intersection.

```bash
moodle course download IOS460                              # everything
moodle course download IOS460 --dry-run                    # preview first
moodle course download IOS460 --section 0 --type resource  # one section, files only
moodle course download H202 --file "Kershaw cap. 7.pdf"    # one specific file
moodle course download H202 --match '*.pdf' -o ~/apuntes   # only PDFs, elsewhere
```

Re-running is safe and cheap: a file already on disk at the expected size is skipped, so an
interrupted download resumes by re-running the same command. Every transfer is verified
against the size the API declares; a truncated or bogus response is reported as a failure
and nothing partial is left behind.

A `--file` name that matches nothing is an error, not a silent zero-file download, and the
message distinguishes a typo from a name excluded by `--section` or `--type`.

### `moodle course participants`

Lists the people enrolled in a course.

| Option | Description |
| --- | --- |
| `--role SHORTNAME` | Filter by role, e.g. `student`, `editingteacher`. |
| `--emails` | Include email addresses. Hidden by default. |
| `--json` | JSON output. |

Email addresses are withheld unless you ask for them, in the table and in the JSON alike.

```console
$ moodle course participants IOS460 --role student
             20 participants in IOS460 - 123246
┏━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━┓
┃ name                 ┃ roles    ┃ last access ┃
┡━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━┩
│ Grace Hopper         │ student  │  2026-07-26 │
└──────────────────────┴──────────┴─────────────┘
```

### `moodle course announcements`

Lists posts from a course's news forum, newest first.

```console
$ moodle course announcements H202
Clase de consulta martes 7 de julio
  2026-07-03 — Pablo Canavessi
  Estimados, les escribo para comunicarles que voy a brindar una clase de
  consulta el martes 7 de 16.30 a 18hs por el zoom del teórico.
```

Only a forum Moodle marks as `"news"` carries announcements; a course's regular discussion
forums are not included, and a course without a news forum prints nothing.

### `moodle course assignments`

Lists a course's assignments and due dates.

```console
$ moodle course assignments H202
          2 assignments in H202 - 119768
┏━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━┓
┃    id ┃ name               ┃        due ┃ grade ┃
┡━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━┩
│ 40393 │ Actividad semana 1 │ 2026-03-11 │ 100.0 │
└───────┴────────────────────┴────────────┴───────┘
```

The `id` column feeds [`moodle course assignment-status`](#moodle-course-assignment-status).

### `moodle course assignment-status`

Shows submission and grading status for one assignment.

```console
$ moodle course assignment-status 40393
submitted: yes (submitted)
graded: yes
grade: 90.00 / 100.00
files:
  Entrega - Semana 1.pdf
```

`assignment-status` takes the `id` printed by `course assignments` — not a course-module
id, which it rejects.

### `moodle course quizzes`

Lists a course's quizzes and their open/close windows.

```console
$ moodle course quizzes H202
              11 quizzes in H202 - 119768
┏━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━┓
┃    id ┃ name                ┃     closes ┃ attempts ┃
┡━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━┩
│ 42628 │ Actividad semana 2  │ 2026-03-19 │        1 │
│ 42941 │ Actividad semana 3  │ 2026-03-25 │        1 │
└───────┴─────────────────────┴────────────┴──────────┘
```

The `id` column feeds [`moodle course quiz-status`](#moodle-course-quiz-status).

### `moodle course quiz-status`

Shows attempt count and best grade for one quiz.

```console
$ moodle course quiz-status 42628
attempts used: 1
last attempt: finished
grade: 6.925 (pass: 4.0)
```

`quiz-status` takes the `id` printed by `course quizzes`.

### `moodle course grades`

Shows the per-item grade breakdown for one course: assignments, quizzes, and the course
total.

```console
$ moodle course grades I204
          Grades for I204 - 101313
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━┓
┃ item                      ┃ grade ┃   max ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━┩
│ TP1                       │ 10.00 │  10.0 │
│ TP2                       │ 10.00 │  10.0 │
│ Examen Final              │  6.00 │ 100.0 │
│ -                         │ 51.50 │ 100.0 │
└───────────────────────────┴───────┴───────┘
```

Fails with a clear error if the instructor has not opened the gradebook to students in
this course; [`moodle courses grades`](#moodle-courses-grades) still works in that case,
just without the per-item detail.

## MCP server

Exposes the same functionality to an agent over stdio.

```bash
claude mcp add moodle -- uv run --project /path/to/moodle-cli moodle-mcp
```

| Tool | Parameters |
| --- | --- |
| `list_courses` | `view` (enum, default `all`), `sort` (enum, default `name`) |
| `get_course_contents` | `course` |
| `search_courses` | `query` |
| `download_course_files` | `course`, `output_dir`, `sections[]`, `module_types[]`, `files[]`, `match[]`, `dry_run` |
| `list_participants` | `course`, `role`, `include_emails` (default `false`) |
| `get_course_announcements` | `course` (default: every enrolled course) |
| `get_assignments` | `course` (default: every enrolled course) |
| `get_assignment_status` | `assignment_id` |
| `get_quizzes` | `course` (default: every enrolled course) |
| `get_quiz_status` | `quiz_id` |
| `get_grade_summary` | — |
| `get_grades` | `course` |

`download_course_files` writes to disk and returns a manifest of paths, sizes and per-file
status. It never returns file contents: a single course can hold hundreds of megabytes, and
the agent can read whatever it needs from disk afterwards. Emails are opt-in here too.

`get_course_contents` includes a `links` entry per module for `url`-type activities (a
recorded-class or external-site link) — the destination is informational, not something
any tool downloads. `search_courses` matches section, activity, file and link names across
every enrolled course in one call, useful for "which course has X" questions.

`get_grades` raises if the instructor has not opened the gradebook to students in that
course; `get_grade_summary` still works in that case, just without per-item detail.

## Configuration

| Variable | Required | Purpose |
| --- | --- | --- |
| `MOODLE_URL` | yes | Campus base URL, e.g. `https://campus.example.edu`. |
| `MOODLE_TOKEN` | no | Use this token directly and skip the keyring. |
| `MOODLE_USER` | no | Username, so `auth login` does not prompt for it. |
| `MOODLE_PASS` | no | Password, for minting a token unattended. |

These can be set in the environment or in a `.env` file at the project root; see
[`.env.example`](.env.example). Token resolution order is `MOODLE_TOKEN`, then the keyring,
then minting a new one from `MOODLE_USER` and `MOODLE_PASS`.

Storing `MOODLE_PASS` is only needed for unattended use. After `auth login` the token lives
in the keyring and the password can be removed.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Success. |
| `1` | API error, authentication failure, unknown course, unknown `--file` name, or one or more downloads failed. |
| `2` | Invalid command line arguments. |

Failures print to stderr, so `--json` output stays parseable.

## Things worth knowing

**Time-based course filters depend on your campus.** `--view in-progress`, `past` and
`future` are computed by Moodle from course start and end dates. Campuses that never set an
end date classify every course you have ever taken as "in progress", which makes
`in-progress` return everything and `past`/`future` return nothing. If that is your case,
use `--view all` or `--view starred` and read the `year` column.

**Filenames are not unique within a course.** Duplicating an activity produces two entries
with the same filename. Byte-identical copies are downloaded once; files that share a name
but differ in size are both kept, with the module id appended to the second.

**Downloads are verified, not assumed.** Moodle answers some failed requests with HTTP 200
and a JSON error body. Written to disk unchecked, that becomes a small JSON file wearing a
`.pdf` name. Every download is checked against its declared size and content type.

**Per-item grades depend on the instructor, not on you.** `course grades` reads the
gradebook detail for one course, which an instructor can leave closed to students. That
shows up as an error, not an empty table — `courses grades` (the course-level summary)
works regardless.

**Assignments and quizzes are separate Moodle activity types.** An "Attempt quiz now"
button is a quiz, not an assignment — `course assignments`/`assignment-status` and `course
quizzes`/`quiz-status` read different web-service functions and do not overlap.

**A `url` module's link is not a file.** `course contents` and `search_courses` show its
actual destination as a `link`, separate from `files`; nothing downloads it, since there is
nothing to download.

## Development

```bash
uv run pytest           # unit tests, no network
uv run pytest --live    # integration tests against a real campus
uv run ruff check .
uv run mypy
```

Unit-test fixtures are synthetic but shape-accurate, reproducing the quirks real campuses
return without committing anyone's personal data. The `--live` suite needs credentials in
the environment and is what catches a campus changing its API underneath the fixtures.
