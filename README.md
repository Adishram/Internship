# Evidence Splitter

A small Python terminal application that converts PDF evidence into positioned HTML,
asks a text model to discover and group process/entity evidence automatically, and provides
process-isolated Q&A with checked citations from the selected process HTML file. Images remain local throughout model calls.

The original brief and detailed requirements remain unchanged in [HANDOFF.md](HANDOFF.md).
The application accepts one user-supplied PDF. No web server, database, vector store,
or agent framework is required.

## Run

Python 3.10 or newer is required. Create a virtual environment and install dependencies:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Launch the terminal workflow:

```sh
.venv/bin/python cli.py
```

At the prompt, drag and drop one PDF into the terminal, or type its full path and
press Enter. Paths with spaces may be typed literally, quoted, or shell-escaped.
Directory input is rejected, and there is no preset document location.

A local preview shows the filename, page count, file size and up to 800 characters
of verbatim first-page text extracted locally by PyMuPDF. This is an excerpt, not
an AI-generated summary. Kitty/iTerm2 terminals also show a first-page thumbnail; other
terminals offer to open the original PDF in the system viewer. Previewing makes no
network requests and happens before credentials are collected.

Enter your API URL, enter the API key at the hidden prompt, and enter a model ID.
For routers with automatic selection, press Enter at the model prompt. `/models`
can list available model IDs. Approve sending document text to that service.

The LLM then discovers the groups automatically. **You do not need to type process
names or supply a target payload.** The LLM reads section headings and identifying
fields to infer which named process/entity each piece of evidence belongs to. The
code contains no predefined process names or fixed preference for server versus
service names. Repeated evidence for the same identity is collected across pages;
start, stop and verification records stay together. Similar or unrelated identities
remain separate. Discovered names must occur exactly in the source evidence, and
previously discovered names are provided to keep naming consistent across sections.

After processing, the terminal lists every created group and its HTML path. Select
a number or group name to chat. `/ls` lists the generated files again. The model
receives only the selected group's HTML evidence and its own conversation history.
Reference images attached to cited sections are displayed locally after answers.

Normal API defaults are Bearer authentication, automatic URL interpretation and
`json_object` responses. For FreeLLMAPI, enter the router's **unified key**; the default
Bearer header is appropriate. These advanced flags are available if your API needs them:

```sh
python cli.py --auth api-key --response-format json_schema --url-type chat
```

Any hosted HTTPS base URL or full OpenAI-compatible chat-completion URL is accepted;
HTTP is also supported for loopback routers. No `/v1` suffix is forced. `--url-type chat`
uses a custom full URL directly, and query parameters such as `api-version` are preserved.
A provider using a different native JSON protocol needs a compatible gateway or adapter.
`auto` as a model name requires router support; direct providers need an exact model ID.

For an explicit fixed list of service/process targets instead of discovery, supply
`--payload targets.example.json`. This optional mode preserves exact supplied labels
and keeps different services separate even if they share a server. It is not part
of the default interactive workflow.

To convert and inspect everything without an API key or any network calls:

```sh
.venv/bin/python cli.py --pdf "/path/to/evidence.pdf" --extract-only
```

Add `--no-browser` to exit after writing the files. Here “browser” means the terminal
document menu; it does not automatically launch a web browser. Local-only exports
mark all evidence as unclassified; no discovered process files are created without a model.

Each run creates `runs/<timestamp>/`:

| Output | Purpose |
| --- | --- |
| `source.html` | Full PDF converted to positioned HTML before classification |
| `index.html` | Links to every target and review document, plus all decision reasons |
| `process-01-group-name.html`, etc. | Independent HTML containing only assigned source evidence |
| `withheld.html` | Uncertain, mixed, unmatched or not-yet-classified evidence |
| `furniture.html` | Recognized document headers/footers, retained for audit |
| `manifest.json` | Source hashes, original pages, positions, section/block/line IDs and decisions |
| `images/` | Actual extracted PNG files with provenance IDs as filenames |

HTML embeds local images at export time so each document can be copied independently.
Outputs contain source evidence; treat them with the same access controls as the PDF.
Keys, endpoint configuration and chat histories are not written to disk.

## Terminal commands

Select any numbered process document, or `w` for withheld evidence. The menu also
provides the results table and index. Inside a document:

| Command | Action |
| --- | --- |
| `/ls` | List every process HTML file, label, size and assigned-section count |
| `/evidence` | Show source text, section chunk numbers, line/block IDs and original pages |
| `/images` or `/images 1` | List numbered local references or immediately show one |
| `/html` | Open this document in the system browser |
| `/chunk N` | Explicitly limit chat to one section, with a separate history |
| `/all` | Restore full-process chat scope |
| `/clear` | Clear the current process/scope conversation history |
| `/process` or `/back` | Return to the document selector |
| `/help`, `/quit` | Show help or exit |

Enter a question to chat. The selected process HTML is read from disk on each question, and only its extracted
evidence text and that process's own history are sent. Missing or modified HTML
fails locally; there is no fallback to another document or in-memory evidence. Withheld evidence is inspectable but cannot be used as process chat evidence.
A response must cite an existing text line ID, the correct section and original page,
and an exact nonempty source quote. Foreign or fabricated citations cause abstention.
**Citation validity does not prove every paraphrase is accurate.** Inspect the quoted
text and original evidence when correctness matters.

Ghostty and Kitty use native Kitty graphics; iTerm2 and WezTerm use inline image
escapes. `/images 1` shows the first image in the selected group immediately, or
say “show me the reference image” to choose one. Answer citations also display their
associated reference images automatically. All image resolution is local and scoped
to the selected group; image bytes never enter LLM requests.

Plain terminals cannot display actual inline images. In that case the CLI gives the
local image path and offers the system viewer when selecting `/images`. Use a compatible
terminal for native display. Multiplexers may block graphics; run directly in the terminal,
or set `EVIDENCE_IMAGE_PROTOCOL=kitty` or `iterm2` only if your setup supports passthrough.
Protocol output is covered by tests; visual rendering requires a compatible terminal.

Ctrl-C cancels the workflow. Conversion is exported before classification begins, so
a provider failure or cancellation leaves a local review document. No partial routing
is published as a successful run. Fix the endpoint/model/quota problem and rerun.

## How the code is organized

There are only two application modules and one test module. Every function has a
purpose docstring; comments explain the main boundaries and security decisions.

- `pipeline.py`: extraction, segmentation, text-only HTTP client, strict JSON/schema
  checks, classification, HTML export, local image resolution and cited chat.
- `cli.py`: prompts, progress, results, document menus, isolated chats and local viewers.
- `test_pipeline.py`: disposable controlled PDFs, mocked HTTP responses and regression tests.
- `requirements.txt` and `targets.example.json`: dependencies and the input payload format.

The backend uses PyMuPDF DICT extraction, retaining line/span coordinates and parent
block IDs. The flow is **PDF → source.html → text extracted from source.html → LLM
classification → independent process HTML files → chat using only the selected HTML**.
The model decides routing; the backend assembles the original HTML evidence according
to those decisions. The model does not rewrite the evidence. HTML is parsed locally
into compact section/block text; markup and base64 images are excluded from requests.
Source IDs and exact text are validated before classification or chat. IDs use
a source-file hash plus original page/block/line numbers. IDs are deterministic for the
same file; rewriting or re-slicing a PDF changes its hash and therefore its IDs.
Filenames like `Synthetic_Server_Data_pages_11-20.pdf` preserve source offsets.
Sections continue across contiguous pages within the selected PDF. A page slice
can be supplied as a single PDF, but missing context remains quarantined.

Segmentation recognizes explicit evidence headings and close markers when present.
Line-level IDs handle headings that share a PDF block with introductory prose. Standalone
large `Start`/`Stop` headings are also recognized. Without these markers, each page
is a candidate section. Discovery sends boundary notes to the model and requires it
to withhold ambiguous/mixed identity; missing-page continuations remain quarantined.
Optional fixed-target mode retains strict boundary quarantine. The furniture allowlist is explicit;
there is no generic “remove repeated bottom rows” rule. Every extracted text/image
unit belongs to a section or the auditable furniture collection.

Classification uses one request per eligible section. A section's associated images
stay attached when the process is clear from text. Mixed evidence is withheld, never
duplicated across targets. There is no confidence cutoff: displayed confidence is a
model estimate, not a measured accuracy score. Routing depends on the model and is
not claimed to be ground truth.

Requests reject authenticated redirects and non-HTTPS remote endpoints, use bounded
timeouts, and validate structured results locally. Invalid JSON/schema gets one
correction attempt; invalid identities and provider errors stop the run. No raw provider
error bodies or tracebacks are printed. A 24,000-character serialized message budget
bounds context conservatively; it is **not a tokenizer or a guarantee for every model**.
Overflow fails without truncation. In chat, use `/evidence` then `/chunk N` to explicitly
inspect a smaller scope, or `/clear` for excessive history. Oversized individual sections
require adjusting evidence boundaries or configuring a suitable budget in `Client`;
they are never silently split or dropped.

## Limits and design choices

Ordinary unmarked pages are evaluated by the model for identity. Pages containing
inseparable evidence for multiple groups are withheld instead of duplicated. New
complex layouts may benefit from additional section boundary rules in `pipeline.py`;
interleaved columns and ambiguous continuations still require review.

Text spans and raster image positions are retained, with browser font fallbacks.
Vector drawings, embedded fonts, rotated text and complex PDF transformations are not
reproduced exactly. Scanned image text is not OCR'd or sent to a vision model. Image-only
identity is therefore withheld. An image overlapping independent sections cannot be
semantically subdivided by this baseline. Always verify unfamiliar layouts against the
source PDF before using their classification downstream.

The preserved 52-page dataset was used for the initial offline verification. The
application has no dependency on that dataset or its local directory. The test
generator creates a smaller known-label fixture rather than a new 30–40-page mock. Automatic group discovery is the default; a web UI is outside this baseline.

Implementation references: [PyMuPDF extraction documentation](https://pymupdf.readthedocs.io/en/latest/app1.html)
explains the positioned text/image representation and HTML layout caveats;
[FreeLLMAPI REST reference](https://github.com/tashfeenahmed/freellmapi/blob/main/docs/en/api/01-rest-api.md)
documents unified authentication, model catalog availability and explicit `auto` routing.
The [Groq compatibility guide](https://console.groq.com/docs/openai) describes its
OpenAI-compatible base path; [Azure REST authentication and versioning](https://learn.microsoft.com/en-us/azure/foundry/openai/reference#authentication)
documents Bearer/`api-key` authentication and `api-version` query parameters.
Model IDs and endpoint availability are runtime configuration, not hardcoded assumptions.

## Tests and verification report — 21 October 2026

```sh
.venv/bin/python -m unittest -v test_pipeline
```

Generate the controlled three-page fixture if you want to inspect it manually:

```sh
.venv/bin/python test_pipeline.py --make-fixture /tmp/evidence-fixture.pdf
```

Its exact targets are `alpha-api` and `beta-api`. It includes a mixed-process page,
a cross-page continuation, repeated table rows, images, mixed and unmatched sections,
and orphan/unknown evidence. Tests generate it in temporary directories automatically.

- Offline regression suite: **41 tests passed**. Tests exercise
  real PDF extraction/export and mock only HTTP responses. Request bodies are inspected
  for text-only content, selected-process isolation and absence of image data/paths.
- Automatic grouping: arbitrary process names across different page counts
  produce separate groups with all original images. CLI tests prove there is no manual
  target prompt; invented/partial labels fail validation. All responses are mocked.
- Native image protocols: Ghostty/Kitty and iTerm2/WezTerm escape output, numbered
  references and isolation are tested without network calls.
- HTML grounding: classification reads the source HTML, chat reads only the selected
  process HTML, and missing/edited/swapped documents are rejected before HTTP.
- Hosted API configuration: base paths, full/custom chat URLs, trailing slashes,
  preserved query parameters, catalog URL construction and both authentication
  headers are verified with mocked HTTP. Embedded URL credentials are rejected.
- Single-PDF input: typed, quoted and shell-escaped paths with spaces are tested.
  Directories and missing files are rejected; preview extracts real PDF metadata/text
  locally and reports corrupt PDFs before model configuration.
- Preserved dataset (initial directory-based verification before single-PDF input): **52 pages, 102 logical sections, 102 extracted images** verified
  locally. The first 100 sections have explicit boundaries. The final two lack close
  markers; discovery now asks the model to assess their available text and boundary notes. Counts are not classification ground truth.
- Error coverage includes invalid JSON/schema, wrong IDs, inconsistent assignments,
  missing/duplicate decisions, provider/auth/quota errors, redirects, context overflow,
  foreign images/citations, fabricated quotes and incorrect source pages.
- Interactive PTY smoke checks: hidden key input did not echo the dummy key; consent
  refusal stopped before network access. A mocked classification run showed real page/section
  progress and accessible process menus. Local image fallback, process switching and
  cancellation were also checked. Actual on-screen graphics rendering and a live-provider waiting
  spinner were not visually verified.
- Live provider classification: **not run**. No document text was disclosed during
  development. Real routing quality and provider-specific structured output compatibility
  remain to be verified after the user's explicit consent in the CLI.
# Internship
