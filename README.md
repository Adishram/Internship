# Evidence Splitter

A small Python terminal application that converts PDF evidence into positioned HTML,
asks a text model to route logical sections to your exact process labels, and provides
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

Enter your hosted API base URL or full chat-completion URL. There is no localhost
default and no required `/v1` suffix. The API must accept the OpenAI chat-completions
request/response format and your chosen structured-response mode.

- `auto` URL type recognizes a URL ending in `/chat/completions`; otherwise it appends
  `/chat/completions` to the supplied base path.
- `base` explicitly uses a base URL; `chat` sends directly to a full custom URL.
- Query parameters such as `api-version` are preserved after the route.
- Choose `bearer` authentication for an Authorization Bearer token, or `api-key` for
  services that require that header. Enter the key/token at the hidden prompt.

Examples of URL formats:

| Input | URL type | Chat URL used |
| --- | --- | --- |
| `https://api.example.com/v1` | `auto` | `https://api.example.com/v1/chat/completions` |
| `https://api.example.com/openai/v1` | `auto` | `https://api.example.com/openai/v1/chat/completions` |
| `https://api.example.com/custom/inference?api-version=VERSION` | `chat` | Used exactly as entered |

Enter an exact model/deployment ID. `/models` attempts the API's catalog route when
it can be inferred; some services do not expose one, so use an explicit ID there.
`/auto` is optional routing offered by some routers, not a universal model name.
Choose `json_object` or `json_schema` according to the provider/model's support.
The program asks for disclosure consent before making any network request. Hosted
and local routers can forward document text to upstream services.

Any hosted HTTPS URL using this compatible format can be configured; provider-specific
native APIs with different JSON formats need an adapter or compatible gateway.
URL flexibility does not imply that every provider/model implements this contract.

Load `targets.example.json`, supply another JSON payload, or choose `/enter` to type
process names. At least two distinct names are required; additional targets work too.
The example labels are `springboot-web` and `springboot-relay`. Replace them with your
actual desired process labels; the program does not silently discover or change targets.
Service start and stop records route to the same process label.

To convert and inspect everything without an API key or any network calls:

```sh
.venv/bin/python cli.py --pdf "/path/to/evidence.pdf" --payload targets.example.json --extract-only
```

Add `--no-browser` to exit after writing the files. Here “browser” means the terminal
document menu; it does not automatically launch a web browser. Local-only exports
mark all evidence as unclassified and leave target documents empty.

Each run creates `runs/<timestamp>/`:

| Output | Purpose |
| --- | --- |
| `source.html` | Full PDF converted to positioned HTML before classification |
| `index.html` | Links to every target and review document, plus all decision reasons |
| `process-01.html`, etc. | Independent HTML containing only assigned source evidence |
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
| `/images` | List local image references and adjacent text, then select an image |
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

Kitty and iTerm2 graphics protocols are supported locally. Other terminals display
the image path and offer to open the system image viewer. A missing or foreign image
ID fails locally without an API request. Actual graphics rendering still needs testing
in a compatible terminal; plain terminal output is not claimed to display an image.

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

Segmentation recognizes the supplied evidence headings and explicit close markers.
Line-level IDs handle headings that share a PDF block with introductory prose. Standalone
large `Start`/`Stop` headings are also recognized. Orphans, missing pages, interrupted
sections and unclosed endings are quarantined. The furniture allowlist is explicit;
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

This baseline is tailored to the supplied structured PDFs. New document layouts may
need explicit heading/close-marker rules in `pipeline.py`. Unmarked continuations,
interleaved columns and unusual reading orders cannot be inferred reliably. Review
quarantined evidence rather than treating it as automatically classified.

Text spans and raster image positions are retained, with browser font fallbacks.
Vector drawings, embedded fonts, rotated text and complex PDF transformations are not
reproduced exactly. Scanned image text is not OCR'd or sent to a vision model. Image-only
identity is therefore withheld. An image overlapping independent sections cannot be
semantically subdivided by this baseline. Always verify unfamiliar layouts against the
source PDF before using their classification downstream.

The preserved 52-page dataset was used for the initial offline verification. The
application has no dependency on that dataset or its local directory. The test
generator creates a smaller known-label fixture rather than a new 30–40-page mock. Automatic process discovery and a web UI are intentionally outside this baseline.

Implementation references: [PyMuPDF extraction documentation](https://pymupdf.readthedocs.io/en/latest/app1.html)
explains the positioned text/image representation and HTML layout caveats;
[FreeLLMAPI REST reference](https://github.com/tashfeenahmed/freellmapi/blob/main/docs/en/api/01-rest-api.md)
documents unified authentication, model catalog availability and explicit `auto` routing.
The [Groq compatibility guide](https://console.groq.com/docs/openai) describes its
OpenAI-compatible base path; [Azure REST authentication and versioning](https://learn.microsoft.com/en-us/azure/foundry/openai/reference#authentication)
documents Bearer/`api-key` authentication and `api-version` query parameters.
Model IDs and endpoint availability are runtime configuration, not hardcoded assumptions.

## Tests and verification report — 13 October 2026

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

- Offline regression suite: **35 tests passed**. Tests exercise
  real PDF extraction/export and mock only HTTP responses. Request bodies are inspected
  for text-only content, selected-process isolation and absence of image data/paths.
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
  markers and remain quarantined. Counts are not classification ground truth.
- Error coverage includes invalid JSON/schema, wrong IDs, inconsistent assignments,
  missing/duplicate decisions, provider/auth/quota errors, redirects, context overflow,
  foreign images/citations, fabricated quotes and incorrect source pages.
- Interactive PTY smoke checks: hidden key input did not echo the dummy key; consent
  refusal stopped before network access. A mocked classification run showed real page/section
  progress and accessible process menus. Local image fallback, process switching and
  cancellation were also checked. Kitty/iTerm2 graphics and a live-provider waiting
  spinner were not visually verified.
- Live provider classification: **not run**. No document text was disclosed during
  development. Real routing quality and provider-specific structured output compatibility
  remain to be verified after the user's explicit consent in the CLI.
# Internship
