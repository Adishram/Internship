# Python implementation: engineering and internship handover

Updated 23 October 2026. Read this alongside `pipeline.py`, `cli.py`, and
`test_pipeline.py`. This document describes the implementation, including the chat
changes made during this handover. `HANDOFF.md` is historical context: later user
requirements supersede its fixed-target default and its earlier exclusion of Rust.
The Python implementation is retained as an independently runnable reference.

## Current delivery status

The final code changes were not built, tested or benchmarked, following the user's
instruction. Earlier test results describe the preceding snapshot, not the final
allocation optimization edits. Python chat packing now extends batches in place,
rolling back only the overflowing unit, while retaining exact budget checks. Each
completion reuses a Draft 2020-12 schema validator across its bounded attempts.
Invalid context-budget flags are rejected before preview/provider configuration.
Rust implementation and its consolidated HTML handover are maintained separately
under `rust/`; publication of this Python handover does not publish that directory.

## 1. Purpose, current contract, and boundaries

The application turns one PDF into HTML, asks a configured text LLM to classify
logical evidence sections, exports one independent HTML per discovered group,
and answers questions using only the selected group's exported evidence.

The default interaction is: PDF path → local preview → API configuration and
consent → conversion → automatic grouping → process list → questions/images.
Users do not need to name processes in advance. `--payload` is an optional
restriction to supplied names. Names and grouping levels come from document text;
there are no hardcoded production process names. The server/service distinction
matters: a model may choose a host as the primary entity, and that group can then
contain multiple services. Review this interpretation before downstream use.

Images are evidence for human inspection. No image pixels, data URLs, attachments,
or image paths go to the LLM. A text-only model cannot read commands or states that
exist solely inside screenshots. There is no OCR. Native terminal image display
does not change the model's capabilities.

The code validates identities, ownership, exact quotes and pages. It cannot prove
that a classification or a paraphrase is semantically correct. Do not describe the
system as having zero hallucinations or use model confidence as measured accuracy.

## 2. Setup from a clean machine

Requirements: Python 3.10+, a terminal, and installed dependencies in
`requirements.txt`. The code has been tested with the repository's Python 3.13
virtual environment; other declared Python versions need their own compatibility
checks. Network access is needed to install packages and for an approved model
connection, but not for extraction or image viewing.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python cli.py
```

Windows activation/launch equivalent:

```powershell
py -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe cli.py
```

Run commands from the repository root. Output goes to `runs/` relative to the
working directory. No user's Desktop, home directory, provider URL, or model ID is
a required deployment path. PDF paths may be typed literally, quoted, or pasted
using terminal drag/drop escaping. A directory is not an input PDF.

First perform a local-only conversion:

```sh
.venv/bin/python cli.py --pdf '/path/to/evidence.pdf' --extract-only --no-browser
```

`--no-browser` exits after exports instead of entering the interactive document
menu; it does not disable the earlier local preview. Review `source.html`,
`withheld.html`, `furniture.html`, and `index.html` in the printed run directory.
Use ordinary filesystem access controls for these files: they contain the PDF's
text and images. Nothing encrypts them automatically.

## 3. Configuration and provider onboarding

| Setting | Default and meaning |
| --- | --- |
| PDF | Prompt or `--pdf`; one existing PDF |
| API URL | Prompt; HTTPS base URL or full compatible chat URL |
| Key | Hidden terminal prompt; retained in memory, never intentionally persisted |
| Model | Prompt; exact provider ID or explicit router `auto` |
| `--auth` | `bearer`; alternatively `api-key` header |
| `--response-format` | `json_object`; alternatively strict `json_schema` |
| `--url-type` | `auto`; `base` appends chat route, `chat` preserves full custom URL |
| `--context-chars` | 24000 serialized message characters; minimum CLI value 4000 |
| `--payload` | Optional JSON file with at least two distinct target strings |
| `--extract-only` | No model configuration or requests |
| `EVIDENCE_IMAGE_PROTOCOL` | Optional `kitty`, `iterm2`, or `none` override |

The character budget is not a token budget. Different languages, escaping, and
models have different tokenization. Set it conservatively below the selected
model's context capacity, allowing space for output. Increasing it does not grant
the model a larger context window. The output allowance is 2048 tokens per call.

Base URLs append `/chat/completions` without adding `/v1` implicitly. A URL already
ending in `/chat/completions` is preserved. Query parameters remain after the path,
including API version parameters. For a custom complete route, use `--url-type
chat`. The catalog route is `/models` under the same base; a custom nonstandard
chat URL cannot imply a model catalog, so supply an exact model ID.

The implemented wire protocol is OpenAI-compatible Chat Completions. A generic URL
field does not implement native Anthropic Messages, Gemini generateContent,
OpenAI Responses, or arbitrary proprietary protocols. Such APIs need a compatible
gateway or a deliberately tested adapter. HTTPS can be remote; HTTP is accepted
only for loopback addresses. Redirects, URL credentials, common secret query names,
fragments, malformed ports and unsafe URL whitespace are rejected.

`/models` filters routes marked `needsKey`, `exhausted`, or equivalent execution
status. Availability may still change after listing. `auto` only works if the
configured service supports it. For a forwarding router, the key may be the
router's unified key rather than its upstream provider's key. Never put real keys
in shell arguments, examples, test fixtures, manifests, bug reports, or commits.

## 4. Files and ownership

| File | Responsibility / likely maintainer changes |
| --- | --- |
| `pipeline.py` | Extraction, segmentation, HTML provenance, HTTP, classification, exports, chat |
| `cli.py` | Input, local preview, progress, menus, terminal images and viewer launch |
| `test_pipeline.py` | Real temporary PDF fixtures and mocked HTTP regressions |
| `requirements.txt` | Reproducible pinned Python dependencies |
| `targets.example.json` | Optional fixed-label payload format |
| `README.md` | Short user entry point |
| `HANDOFF.md` | Original brief and historical decisions |
| `PYTHON_MAINTENANCE.md` | This technical operations guide |
| `rust/` | Independent native implementation; see its own handover |

There is no web server, database, scheduler, queue, vector store, model training,
or background ingestion process. A run is local files plus in-memory application
state. A second user should run their own process and output directory. Importing
a manifest and resuming a prior Python run is not currently a CLI feature.

## 5. End-to-end execution and failure boundaries

1. `main()` parses flags; `select_pdf()` normalizes and validates the path.
2. `preview_pdf()` reads the first page locally. The shown excerpt is verbatim
   extraction, not an AI summary. Graphics-capable terminals get a local thumbnail;
   other interactive terminals offer the system viewer.
3. `configure()` gathers endpoint, key and model, then asks for explicit consent.
   No evidence request precedes that approval. Catalog requests also require it.
4. `extract()` creates the run and image directory, validates PDF/page metadata,
   hashes the file, extracts positioned units, calls `segment()`, and writes
   `source.html` before classification starts.
5. `export(..., state='not classified')` creates a reviewable local baseline.
   All sections are withheld; this is not successful routing.
6. `classify()` reads and validates `source.html`, routes eligible sections one at
   a time, validates each result, and reports real completed section counts.
7. Only complete valid decisions are passed to `export(..., state='complete')`.
   It assembles source evidence into independent documents; the model never writes
   or rewrites the HTML evidence.
8. `browse()` lists processes, withheld evidence, index and decisions. A question
   invokes `Chat.ask()` for the selected document. Images are resolved locally.

A provider failure stops classification rather than producing a stream of false
uncertain labels. The previous local baseline remains inspectable. A filesystem
failure during export can leave partial files: exports are not transactional.
Check `manifest.json` state and all referenced files; do not infer completeness
from a directory existing. New runs use new timestamp directories, avoiding reuse
of old successful output as if it belonged to a failed run.

## 6. Data model and provenance invariants

`data` contains `sources`, `pages`, `sections`, and `furniture`. The manifest adds
`state`, `targets`, `documents`, and `decisions`.

- Source: filename, full SHA-256, starting original page, count, and family name.
- Page: deterministic ID, original page number, source/family, width/height, units.
- Text unit: ID, parent `block_id`, page/page ID/source, bounding box, text, spans.
- Span: original text, rectangle, font size, flags and color.
- Image unit: analogous provenance plus relative PNG path, no extracted text.
- Section: ID based on its first unit, ordered units, and optional boundary note.
- Decision: `section_id`, `status`, nullable `target`, confidence in [0,1], reason.

Example ID shape: `d<12 hex hash>-p0007-b003-l001`. `b003` is a PDF block and
`l001` identifies a text line within it. A section adds `s-`. Image IDs generally
end at the parent block. A file rewrite changes the hash even if its appearance
is similar; IDs are not durable business identifiers across independently saved
PDF versions. A `_pages_11-20.pdf` filename supplies original page offset 11 and
must contain exactly ten pages. Without that convention, page numbering starts
at one. The application cannot reconstruct omitted pages from a slice.

Every extracted unit must be owned by exactly one section or furniture. Furniture
is an explicit allowlist of known headers/footers; repeated table rows are evidence
and must not be dropped by a generic repetition heuristic. Source image paths
must resolve inside this run's image directory before local display.

HTML wrappers carry `id`, `data-section`, `data-block`, and `data-page`. Text is
escaped; images are embedded as PNG data URLs for standalone copying. `read_html()`
parses known wrappers and checks exact text, page and ownership against in-memory
source provenance. It rejects missing, duplicate, foreign or modified evidence.
Titles/CSS/image bytes are not context. This detects evidence mismatches, not
malicious modification of the entire source-and-manifest trust base. Never treat
arbitrary downloaded manifests as authenticated evidence.

## 7. Segmentation and classification policy

`is_heading()` recognizes explicit evidence headings and sufficiently large
standalone Start/Stop headings. `segment()` carries open sections across contiguous
pages and finishes at explicit close markers. Orphans, interrupted sections,
missing pages and missing close markers receive boundary notes. If the document
has no recognized heading anywhere, each page is an independent candidate.

Discovery sends ordinary boundary notes to the model for conservative assessment;
missing/unrelated continuation pages remain locally withheld. Optional fixed-label
mode withholds every ambiguous boundary before calling the model. A mixed page
with separable recognized sections can be routed independently. An unmarked page
containing inseparable different identities must be withheld as mixed. More robust
column/layout analysis would be a future feature, not a reason to guess today.

Discovery provides `known_groups` to encourage consistent names. An assigned label
must occur exactly at an identifier boundary in source text, be printable, trimmed,
and at most 200 characters. This prevents fabricated or partial identifiers but
does not decide whether host, service or business process is the right grouping
level. The model makes that choice. Review wrong groupings in the manifest before
changing the segmentation rules.

Statuses: `assigned` requires a valid target; `mixed`, `uncertain` and `unmatched`
require null target. No duplicate assignment to two outputs is permitted. Confidence
is displayed for review; there is no confidence threshold implying correctness.

## 8. Chat behavior and the reported failure

The reported message was “Abstained: the selected evidence did not support a
reliable answer,” for “has the process relay-44 started and stopped?” This message
came from a schema-valid model response with `abstain: true`; it was not a network
exception or an HTTP error. The previous code discarded the model's answer and
showed a generic abstention. An unsupported model explanation must not become a
trusted factual answer just because it is attached to an abstention.

Offline inspection of the latest saved run found a group containing explicit stop
records for two services, plus health/maintenance records, without an explicit start
record. This explains why the old instruction to abstain when evidence was missing
could suppress the entire multipart answer. It does not prove the live model's
internal reason. A useful grounded answer confirms the documented stop and states
that the supplied text does not establish the start; it does not infer “never
started,” nor conflate multiple services under one host.

The revised generic instruction answers supported parts of multipart questions,
identifies unsupported parts, distinguishes services within a group, and does not
regard start/stop at different times as inherently contradictory. It contains no
special-case process names or operation-response shortcuts.

Additional robustness changes:

- Every question re-reads only the selected process HTML and validates it.
- Chat labels parent identifiers `parent_block_id`; citations should use text `id`.
- A parent ID returned by a model can be normalized only when section, page and
  exact quote identify exactly one text line in the current request. Ambiguity fails.
- Invalid citation semantics get one bounded correction request. Invalid quotes,
  foreign IDs or pages still cannot pass. Raw failed outputs are not printed.
- Recent history is limited to four turns and at most one quarter of the budget.
  If older history is omitted, the CLI tells the user; evidence is not omitted.
- When the selected process is too large, every original unit is visited in bounded
  batches. A section can be split at unit boundaries. Every request stays within
  the configured serialized character budget and leaves room for corrections.
- Batch answers are explicitly labeled, individually cited and displayed together.
  They are not synthesized into an unsupported global conclusion. A missing fact
  in one batch does not mean it is absent from other batches. Cross-batch conflicts
  and chronology require reviewing the returned evidence; this is a deliberate
  limitation of the small implementation.
- Any invalid batch causes the entire question to abstain. API failures propagate
  without presenting a partial result as success. No failed batch is silently skipped.
- An individual huge line/question still produces an actionable budget error;
  it is never silently truncated. Use `/clear`, a smaller question, or a suitable
  higher budget. `/chunk N` remains an explicit smaller scope with separate history.

History keys are `(target, chunk)`. Different process chats, full process chat and
section chat do not share histories. Answers and history are memory-only. All
factual answers require nonempty validated citations. An image reference is never
a valid quoted text citation. Abstaining outputs are replaced with local guidance
rather than displaying unchecked assertions from the model.

## 9. HTTP and structured result handling

Only `Client` uses HTTP. `request()` enforces consent, allowed URLs, auth headers,
no redirects, ten-second connection timeout and ninety-second read timeout.
Requests has no application-level automatic retry here. Provider bodies and raw
transport exceptions are suppressed to avoid exposing secrets or source text.

`complete()` constructs system/user messages, embeds the JSON schema, requests a
result instance, sets temperature zero and output limit 2048, then parses the
Chat Completions envelope. A single enclosing JSON fence is tolerated. Arbitrary
prose around JSON, nonfinite numbers, extra fields and wrong types are rejected.
JSON/schema failure receives one correction; truncated output and transport errors
do not. Chat citation repair is a separate semantic stage, so a batch can consume
up to four HTTP completions when both repairs are needed. Classification gets at
most two completions per eligible section. Budget checks precede each request.

## 10. Output and terminal operation

| Artifact | Meaning |
| --- | --- |
| `source.html` | All converted evidence plus audited furniture |
| `process-NN-<slug>.html` | Only the selected target's assigned original units |
| `withheld.html` | Everything not assigned |
| `furniture.html` | Explicitly recognized non-evidence text, retained for audit |
| `index.html` | Links and classification decision table |
| `manifest.json` | Full original provenance and decisions; no credentials |
| `images/*.png` | Locally extracted image references |

Blank areas in a process HTML preserve source positioning where other evidence was
removed. Text spans/raster images are retained; fonts, vector drawings, arbitrary
rotations and complicated transforms are not guaranteed pixel-perfect.

Menu: number/name selects a group, `w` inspects withheld, `r` shows decisions, `i`
opens index, `/ls` lists files. Within a group: `/evidence`, `/images [number or ID]`,
`/html`, `/chunk N`, `/all`, `/clear`, `/back`, `/process`, `/help`, `/quit`.
`/ls` uses Python filesystem listing; it does not execute untrusted shell strings.

Ghostty/Kitty use Kitty graphics; iTerm2/WezTerm use OSC 1337. Redirected stdout and
unsupported terminals receive paths instead. Multiplexers may block protocols;
use a directly supported terminal or a deliberately configured override. Missing
images produce local errors. Citation-associated images display after answers
without sending pixels to the API. A successful escape write is not proof of
visual display; verify on the actual user's terminal.

## 11. Troubleshooting decision table

| Symptom | Check and recovery |
| --- | --- |
| Model abstains | `/evidence`: is the requested fact present as text in this selected group? Try a specific supported part. Check screenshots via `/images`. Review grouping and missing PDF slices. Do not remove validation to force answers. |
| Unsupported/foreign citations | Confirm line IDs and exact quotes; one repair is automatic. Repeated failures suggest model/prompt compatibility; inspect a sanitized synthetic reproduction. |
| Context budget error | `/clear`; shorten question; choose `/chunk N`; increase `--context-chars` only within actual model capacity. Check for exceptionally long individual lines. |
| HTTP 401 / 403 | Check router versus provider key and `--auth`; verify access. Never print the key. |
| HTTP 404 | Correct complete route, base prefix and exact model ID. |
| HTTP 400 | Check structured response support, model parameters and context limits. Try the explicitly supported JSON mode. |
| HTTP 429 | Stop; inspect quota/rate limits and retry later or choose available model. |
| Redirect refused | Enter the final trusted endpoint directly. |
| Network/TLS failure | Confirm endpoint, certificates, proxy and reachability; do not disable TLS checks. |
| Truncated model output | Reduce scope or choose appropriate model/output capacity; inspect 2048-token setting in `complete()`. |
| Invalid JSON/schema after repair | Provider may echo schema or add fields; use synthetic data to evaluate compatibility. |
| HTML modified/missing/foreign | Reconvert source. Do not bypass integrity checks or use another process's HTML. |
| Wrong groups | Inspect decisions and original text; adjust generic segmentation/prompt or provide explicit payload. |
| All image-only pages withheld | Expected without OCR; add a tested local OCR stage only as a separate requirement. |
| Image path but no graphic | Terminal/protocol limitation, not LLM failure; use compatible terminal or local viewer. |
| Generic local failure | Check PDF validity, output write permission, disk, dependency versions; reproduce using synthetic fixture under a debugger without real keys. |

Collect for an issue: version/commit, OS/Python, command flags without secrets,
question, selected label, safe error text, source section/page IDs, run state and
a sanitized small reproduction. Do not attach production PDFs, manifests or raw
HTTP headers by default. Ask the owner which evidence can be shared.

## 12. Tests and maintenance workflow

```sh
.venv/bin/python -B -m unittest -v test_pipeline
.venv/bin/python test_pipeline.py --make-fixture /tmp/evidence-fixture.pdf
```

An earlier Python snapshot passed **44 tests**; the final allocation edits were not retested. Tests create actual PDFs in
temporary directories and mock only HTTP. They cover
mixed pages, cross-page sections, repeated rows, source offsets, all-block
conservation, image ownership, real HTML export/read-back, modified/missing HTML,
provider errors, authentication modes, URL/query composition, malformed JSON,
schema errors, invalid IDs/status pairs, quotation validation, isolation, explicit
chunk scope, batch coverage and history bounds. Graphics tests inspect protocol
bytes, not a screenshot of terminal rendering. CLI tests prove automatic discovery
has no target-name prompt. The mock oracle is test data, not a production classifier.

For a segmentation change, first create a PDF fixture showing the failing layout;
assert every unit appears exactly once in sections/furniture and no process acquires
foreign evidence. For a chat change, inspect serialized mock request bodies and
assert no other process, image bytes or paths are sent. Include accepted and
rejected citations, not just a golden successful response. For a provider change,
mock HTTP errors/redirects and response envelopes before a live synthetic smoke test.

Run the full Python suite after shared backend edits. Record the exact test result,
not a copied historical count. A passed mock suite does not establish live model
accuracy. Live reproduction of the reported abstention requires the user's provider
and approved synthetic/sanitized data; no key was available during this handover.

## 13. Operations, upgrades, and next-intern checklist

1. Start by reading the short README and this guide, then run all tests.
2. Make one local extraction and inspect text, images, order, page numbering and
   withheld boundaries against the original PDF.
3. Use a controlled synthetic PDF with known outcomes for the first provider test.
   Record model ID, response mode and reviewed expected answers without secrets.
4. Test a compound question where one part is missing: confirm the supported part
   is answered with quotes and the missing part is not invented.
5. Test an unsupported question and foreign image/citation request: expect refusal.
6. Check terminal graphics on the deployment terminal and fallback behavior.
7. Measure extraction, export and model wait separately. Do not attribute network
   latency to Python or assume a language rewrite improves provider responses.
8. Review dependency upgrades one at a time. Keep pinned versions and regenerate
   fixtures only intentionally; extraction changes can alter unit IDs/boundaries.
9. Back up source PDFs and required run directories according to the organization's
   policy. Delete old runs explicitly when permitted; the app has no retention job.
10. Retain the previous code/environment for rollback; new code should use a new
    run. Never mix old manifests with regenerated HTML or images.

Known extension points: local OCR with provenance, more general layout segmentation,
explicit grouping-level configuration, resume/import validation, cross-batch
synthesis with conflict verification, context token counting per model, safe
structured diagnostics, measured accuracy evaluation, transactional exports, and
controlled parallel classification for fixed targets. They are future work, not
features to imply already exist. Keep the current minimal design until a measured
problem warrants additional infrastructure.
