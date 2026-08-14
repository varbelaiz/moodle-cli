# moodle-cli-anydoc

Converts a course document to GitHub-Flavored Markdown, via
[anydoc](https://github.com/firecrawl/anydoc): Word, PowerPoint, Excel, OpenDocument, RTF,
EPUB, CSV and PDF.

```bash
moodle plugins install anydoc
```

See [docs/plugins.md](../../docs/plugins.md) in the core repository for how plugins are
installed and discovered in general.

Two capabilities, split by what each is for rather than just by input shape:

- **`convert`** transforms a batch of files already on disk. Purely local — no client, no
  token, no network. Returns paths, not content: this is for persisting output (a vault,
  a course archive), not reading any one file back.
- **`fetch`** reaches the campus itself for a single named file, going through the same
  download machinery `moodle course download` uses — a file already on disk at the
  expected size is reused rather than re-fetched. Returns the markdown content inline, so
  reading one course document takes one call instead of a download-then-convert dance.

Both accept `--ocr`, an opt-in that trades the local converter for Firecrawl's hosted
`/parse` endpoint. The local converter is purely structural — it finds no text in a
scanned page or a slide that's mostly a screenshot. Firecrawl Parse adds OCR models that
recover that content. Forcing OCR only works for a PDF, since that is the only format
Firecrawl's API exposes OCR control for — for a raw `.pptx`/`.docx`, `--ocr` still routes
the file through Firecrawl Parse but cannot force OCR on it, so a slide deck uploaded as
`.pptx` rather than an exported PDF may still convert thin. Requires `FIRECRAWL_KEY` in
the environment or `.env`; without it, `--ocr` fails with a clear error rather than
silently converting locally instead. It is never the default — sending course material
to a third-party API should be a choice you make per file, not something that happens
implicitly.

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

```
moodle anydoc convert --ocr PATH...
```

Converts via Firecrawl Parse instead of locally. Requires `FIRECRAWL_KEY`.

Example output:

```
ok    IOS460/Programa.pdf -> IOS460/Programa.pdf.md
FAIL  IOS460/scan.pdf: encrypted or password-protected
```

## `anydoc_convert_to_markdown`

MCP tool. Same conversion, for an agent building up a batch of files already on disk —
for example, exporting a course into an Obsidian vault. `ocr: true` converts via
Firecrawl Parse instead of locally; requires `FIRECRAWL_KEY`.

```json
{"paths": ["IOS460/Programa.pdf", "IOS460/Semana 1/slides.pptx"]}
```

Returns a path-only manifest, one entry per input, in order:

```json
[
  {"path": "IOS460/Programa.pdf", "markdown_path": "IOS460/Programa.pdf.md", "status": "converted"},
  {"path": "IOS460/Semana 1/slides.pptx", "status": "error", "error": "...: encrypted or password-protected"}
]
```

## `moodle anydoc fetch`

```
moodle anydoc fetch COURSE FILENAME [--section N] [--ocr]
```

Fetches one file by course and exact filename (as shown by `moodle course contents`),
converts it, and writes `<name>.md` alongside it. `--section` disambiguates the rare case
where a duplicated activity produces two files under the same name with different sizes.
`--ocr` converts via Firecrawl Parse instead of locally; requires `FIRECRAWL_KEY`.

## `anydoc_get_markdown`

MCP tool. Same fetch, for an agent asking about one course document — a slide, a handout
— without a prior download step. `ocr: true` converts via Firecrawl Parse instead of
locally — useful once a local conversion of the same file came back thin (a scanned
page, an image-heavy slide); requires `FIRECRAWL_KEY`.

```json
{"course": "IOS460", "filename": "Programa.pdf"}
```

Writes `<path>.md` and returns both the file it wrote and the markdown itself, so reading
a course document takes one call:

```json
{
  "path": "IOS460/Programa.pdf",
  "markdown_path": "IOS460/Programa.pdf.md",
  "markdown": "# Programa...",
  "truncated": false
}
```

`markdown` is capped at 20,000 characters. `truncated` is true when the file converted to
more than that — an agent with filesystem access reads `markdown_path` directly for the
rest, the same way `download_course_files` expects a large file to be read from disk
rather than through the tool response.

Raises if `course` or `filename` do not resolve, if `filename` matches more than one file
in the course (see `section`), or if the file cannot be converted.
