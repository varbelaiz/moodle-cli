# Browsing and searching courses

## List enrolled courses

CLI: `moodle courses list`
MCP: `list_courses`

```
moodle courses list [--view VIEW] [--sort SORT] [--json]
```

- `--view` — which courses to include: `all`, `all-including-hidden`, `in-progress`,
  `future`, `past`, `starred`, `hidden`. Default `all`.
- `--sort` — ordering: `name`, `last-accessed`. Default `name`.
- `--json` — emit JSON instead of a table.

MCP parameters: `view` (same enum, default `all`), `sort` (same enum, default `name`).

The table shows id, shortname, name, start year and a starred marker; `--json` and the
MCP tool additionally carry `category`, `hidden` and a `url` to the course page.

**Time-based filters depend on your campus having end dates configured.** A campus that
never sets one classifies every course as "in progress": `--view in-progress` returns
everything and `past`/`future` return nothing. If that's the case, use `all` or `starred`
and read the start year instead.

## Show one course's contents

CLI: `moodle course contents`
MCP: `get_course_contents`

```
moodle course contents COURSE [--json]
```

`COURSE` is a numeric id or a shortname prefix; a prefix matching more than one course is
an error listing the candidates. This applies to every command below that takes a course.

Shows the course's sections, activities, downloadable files and external links. Activities
without downloadable files — forums, quizzes, assignments — are listed without file
entries. Filenames printed here can be passed verbatim to `course download --file` or
`download_course_files`'s `files` parameter.

**A `url`-type module's link is not a file.** It's an external link (a recorded-class
platform, a third-party site) shown as its own entry with a destination, separate from
`files`: nothing downloads it, since there's nothing to download.

## Search across every course

CLI: `moodle courses search`
MCP: `search_courses`

```
moodle courses search QUERY [--json]
```

MCP parameter: `query`.

Searches section, activity, file and link names across every enrolled course at once,
including ones hidden from the dashboard — answers "which course has X" without reading
each course in turn. The match is a case-insensitive substring; a link matches on its
destination as well as its label, so a bare domain finds it.

Each result names what was hit — a section, an activity name, a file, or a link — under
`match`, which changes what the rest of the result means: on an activity-name hit, the
files/links listed are that activity's whole contents; on a file or link hit, only the
matching entries. Results are capped; a query that hits the cap says so and wants
narrowing rather than paging.

Every result carries a section number, which feeds directly into `course download
--section` / `download_course_files`'s `sections` parameter.
