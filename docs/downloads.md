# Downloading files

CLI: `moodle course download`
MCP: `download_course_files`

```
moodle course download COURSE [--output, -o PATH] [--section N] [--type TYPE]
                        [--file NAME] [--match GLOB] [--dry-run] [--overwrite]
```

| Option | Description |
| --- | --- |
| `--output`, `-o PATH` | Destination directory. Default `./<shortname>/`. |
| `--section N` | Only this section number. Repeatable. |
| `--type TYPE` | Only these module types, e.g. `resource`, `folder`. Repeatable. |
| `--file NAME` | Exact filename, as shown by `course contents`. Repeatable. |
| `--match GLOB` | Case-insensitive glob on the filename, e.g. `'*.pdf'`. Repeatable. |
| `--dry-run` | List what would be downloaded and write nothing. |
| `--overwrite` | Re-download files that already exist. |

MCP parameters: `course`, `output_dir`, `sections[]`, `module_types[]`, `files[]`,
`match[]`, `dry_run`. There is no `overwrite` on the MCP side.

Downloads a course's files, mirroring its section structure; Moodle folders become nested
directories. `--section`/`sections` and `--type`/`module_types` narrow by structure,
`--file`/`files` and `--match`/`match` by filename — all four compose by intersection. A
`--file`/`files` name that matches nothing is an error, not a silent zero-file download,
and the message distinguishes a typo from a name excluded by another selector.

Re-running is safe and cheap: a file already on disk at the expected size is skipped, so
an interrupted download resumes by re-running the same command. Every transfer is
verified against the size the API declares; a truncated or bogus response is reported as
a failure and nothing partial is left behind.

The MCP tool writes to disk and returns a manifest of paths, sizes and per-file status —
never file contents. A course can hold hundreds of megabytes; read whatever is needed
from disk afterwards instead.

Example CLI output (not `--json`; there is no JSON mode for this command):

```
CS101: 2 files, 4.9 MB -> CS101/
  ok    Week 1/syllabus.pdf (200.0 KB)
  skip  Week 1/slides.pdf

2 downloaded, 1 already present
```

Example `download_course_files` response with `dry_run: true`:

```json
{
  "course": "CS101",
  "directory": "CS101",
  "dry_run": true,
  "files": [
    {"path": "CS101/Week 1/syllabus.pdf", "size": 204800, "module_type": "resource", "status": "planned"}
  ]
}
```

A real run replaces `dry_run` with a `summary`, and each file's `status` becomes
`downloaded`, `skipped`, or `failed` (with an `error` message):

```json
{
  "course": "CS101",
  "directory": "CS101",
  "summary": {"downloaded": 1, "already_present": 0, "failed": 0},
  "files": [
    {"path": "CS101/Week 1/syllabus.pdf", "size": 204800, "module_type": "resource", "status": "downloaded"}
  ]
}
```
