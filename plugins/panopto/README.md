# moodle-cli-panopto

Lists a course's Panopto-hosted class recordings and converts their auto-generated
transcripts to markdown.

```bash
moodle plugins install panopto
```

See [docs/plugins.md](../../docs/plugins.md) in the core repository for how plugins are
installed and discovered in general.

**Needs `MOODLE_USER`/`MOODLE_PASS`.** The web-service token this tool otherwise runs
on covers none of what Panopto needs: recordings are listed through the course's own
Panopto block (an internal Moodle endpoint, not part of the web-service surface), and
the transcript itself lives on a separate Panopto host reached only through the
course's Panopto "External tool" activity. This plugin logs in with a cookie the same
way a browser tab does, then replays that LTI launch to establish its own session with
Panopto — a `MOODLE_TOKEN` alone cannot do either.

"Polishing" a transcript means mechanical formatting only: consecutive captions are
grouped into paragraphs on a pause of 2 seconds or more, each marked with a
`**HH:MM:SS**` timestamp. The transcribed text itself is never reworded.

## `moodle panopto list`

```
moodle panopto list COURSE [--json]
```

Lists a course's recordings — delivery id and display name. Cheap: this never reaches
a Panopto host, only the course's own Panopto block.

Example output:

```
e7864c25-59dc-47c5-993a-b4a300033c23  Class 1 - Introduction
a20d282d-17d7-46b7-a52a-b49c000734d4  Class 2 - Backend development
```

## `moodle panopto download`

```
moodle panopto download COURSE [--session ...] [--match ...] [--language N]
                         [--output DIR] [--dry-run] [--overwrite]
```

| Option | Description |
| --- | --- |
| `--session` | Exact delivery id or display name. Repeatable. |
| `--match` | Glob on the display name, e.g. `'*week 1*'`. Repeatable. |
| `--language` | Caption language code, if the recording has more than one. Read from the recording's own captions by default. |
| `--output`, `-o` | Destination directory. Default: `./<shortname>/Panopto/`. |
| `--dry-run` | List what would be written, write nothing. |
| `--overwrite` | Re-fetch transcripts that already exist. |

Fetches and writes every matching recording's transcript as `<name>.md`. `--session`
and `--match` compose as a union, exactly like `moodle course download`'s `--file` and
`--match`; without either, every recording in the course is fetched. One recording
failing does not stop the rest of the batch.

Example output:

```
ok      Class 1 - Introduction -> IOS460/Panopto/Class 1 - Introduction.md
skip    Class 2 - Backend development
FAIL    Class 3 - Live now: no captions in any language
```

## `moodle panopto get`

```
moodle panopto get COURSE SESSION [--language N]
```

Fetches one session's transcript and prints it to stdout — writes nothing to disk.
`SESSION` accepts an exact delivery id or a name substring; matching zero or more than
one recording is an error.

## `panopto_list_recordings`

MCP tool. Same listing as `list`.

```json
{"course": "IOS460"}
```

```json
[{"id": "e7864c25-59dc-47c5-993a-b4a300033c23", "name": "Class 1 - Introduction"}]
```

## `panopto_download_transcript`

MCP tool. Same batch fetch as `download`, for an agent building up a course's
transcripts on disk. `session` narrows to one recording; omitted, every recording in
the course is fetched. Returns a path-only manifest, no content:

```json
{"course": "IOS460"}
```

```json
[
  {"id": "e7864c25-...", "name": "Class 1 - Introduction", "status": "downloaded", "path": "IOS460/Panopto/Class 1 - Introduction.md"},
  {"id": "a20d282d-...", "name": "Class 3 - Live now", "status": "error", "path": null, "error": "this recording has no captions in any language"}
]
```

## `panopto_get_transcript`

MCP tool. Same single fetch as `get`, plus a disk write — for an agent asking about one
class without a prior download step.

```json
{"course": "IOS460", "session": "Introduction"}
```

Writes `markdown_path` and always returns that full path; `markdown` is capped at
20,000 characters, with `truncated` true when the transcript runs longer:

```json
{
  "markdown_path": "IOS460/Panopto/Class 1 - Introduction.md",
  "markdown": "# Class 1 - Introduction\n\n**00:00:06**\n...",
  "truncated": false
}
```

Raises if `course` or `session` do not resolve, if `session` matches more than one
recording, or if `language` is omitted while more than one caption language is
available.
