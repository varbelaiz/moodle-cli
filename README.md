# moodle-cli

A CLI and MCP server for a Moodle campus. Lists your courses, reads their contents,
downloads the material, and shows who is enrolled — over Moodle's web-service API, with no
browser and no HTML scraping.

Built against Universidad de San Andrés's campus (Moodle 5.1), but the client is generic:
point `MOODLE_URL` at any Moodle instance with web services enabled.

## Install

```bash
uv sync
```

## Authenticate

Set the campus URL and your credentials, then mint a token:

```bash
cp .env.example .env   # then fill in MOODLE_URL, MOODLE_USER, MOODLE_PASS
uv run moodle auth login
```

`auth login` exchanges your password for a long-lived web-service token and stores it in the
system keyring. **Once that succeeds you can delete `MOODLE_PASS` from `.env`** — nothing
else needs it.

Credential resolution order is `MOODLE_TOKEN` → keyring → mint from `MOODLE_USER`/`MOODLE_PASS`,
so an explicitly exported token always wins.

```bash
uv run moodle auth status    # who am I, and what can this token do
uv run moodle auth logout    # drop the stored token
```

## Use

```bash
# Courses
moodle courses list
moodle courses list --view starred --sort last-accessed
moodle courses list --json

# A single course, by id or shortname prefix
moodle course contents IOS460
moodle course participants IOS460 --role student

# Downloads land in ./<shortname>/, mirroring the course's sections
moodle course download IOS460 --dry-run
moodle course download IOS460
moodle course download IOS460 --section 0 --type resource --output ~/apuntes
```

Every read command takes `--json`.

### Participant emails

The API returns an email address for every enrolled person. `course participants` withholds
them unless you pass `--emails`, in both the table and the JSON output.

## MCP server

Exposes `list_courses`, `get_course_contents`, `download_course_files` and
`list_participants` over stdio. Register it with:

```bash
claude mcp add moodle -- uv run --project /path/to/moodle-cli moodle-mcp
```

`download_course_files` writes to disk and returns a manifest of paths — never file contents,
which would flood the agent's context. Emails are opt-in there too.

## Campus quirks this handles

**The API fails with HTTP 200.** A bad login, a rejected web-service call, and an
unauthenticated file download all return status 200 with an error payload in the body. Any
client that trusts `raise_for_status()` will write a 141-byte JSON error to disk named
`Programa.pdf` and report success. Every response is checked for an error body, and every
download is validated against the `filesize` and content type the API declares.

**Course end dates are never set.** All courses report `enddate = 0`, so Moodle classifies
every course you have ever taken as "in progress". `--view in-progress` returns everything
and `--view past` / `--view future` return nothing. The flags exist because they are valid
Moodle, but only `all`, `starred` and `hidden` discriminate here — use the `year` column to
judge recency.

**Bibliography files are flagged `isexternalfile`.** They live in an external repository but
are still served through `pluginfile.php`, so they are downloaded like any other file.
Filtering them out silently loses most of a course's reading material.

## Develop

```bash
uv run pytest           # unit tests, no network
uv run pytest --live    # smoke tests against the real campus
uv run ruff check .
uv run mypy
```

Unit-test fixtures are synthetic but shape-accurate: they reproduce the campus's quirks
(null `filepath`, doubled `.pdf.pdf` extensions, external-file flags) without committing real
classmates' names or addresses. The `--live` suite is what catches the campus changing its
API underneath the fixtures.

## Not implemented

Recorded lectures and their transcripts live in Panopto, not Moodle — the "Clases Grabadas"
activity is an LTI launch into `udesa.hosted.panopto.com`. That needs a separate auth flow
and is not covered here. Assignments and grades are also out of scope.
