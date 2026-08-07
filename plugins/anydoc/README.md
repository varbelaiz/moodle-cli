# moodle-cli-anydoc

Converts a course file already on disk to GitHub-Flavored Markdown, via
[anydoc](https://github.com/firecrawl/anydoc): Word, PowerPoint, Excel, OpenDocument, RTF,
EPUB, CSV and PDF. Purely local — this plugin never reaches the campus, so it needs no
token and no client.

```bash
moodle plugins install anydoc
```

See [docs/plugins.md](../../docs/plugins.md) in the core repository for how plugins are
installed and discovered in general.

## `moodle anydoc convert`

```
moodle anydoc convert PATH...
```

Converts one or more files, as put on disk by `moodle course download`, writing
`<name>.md` next to each. Appends rather than replaces the extension — a course that has
`Programa.pdf` and `Programa.docx` under one stem gets `Programa.pdf.md` and
`Programa.docx.md`, not one file overwriting the other.

One file failing (corrupt, encrypted, or a format anydoc does not recognize) does not
stop the rest of the batch; it is reported to stderr and the command exits non-zero once
the batch finishes.

Example output:

```
ok    IOS460/Programa.pdf -> IOS460/Programa.pdf.md
FAIL  IOS460/scan.pdf: encrypted or password-protected
```

## `anydoc_convert`

MCP tool. Same conversion, for an agent reading a course document already on disk.

```json
{"path": "IOS460/Programa.pdf"}
```

Writes `<path>.md` and returns both the file it wrote and the markdown itself, so reading
a course document takes one call instead of a convert-then-read round trip:

```json
{
  "path": "IOS460/Programa.pdf",
  "markdown_path": "IOS460/Programa.pdf.md",
  "markdown": "# Programa...",
  "truncated": false
}
```

`markdown` is capped at 20,000 characters. `truncated` is true when the file converted to
more than that — read `markdown_path` for the rest, the same way `download_course_files`
expects the caller to read a large file from disk rather than through the tool response.

Raises if `path` does not exist or cannot be converted.
