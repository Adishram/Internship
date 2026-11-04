# Evidence Splitter: Python implementation handbook

Updated 4 November 2026. This is the reference for the Python application, including local OCR and heading-led documents. The separate Rust application is not the implementation described here. Names in examples are illustrative, never built-in routing targets.

## Purpose and trust boundary

The application accepts one PDF, preserves its native text and embedded raster images, transcribes those images locally, and produces separate HTML evidence files for named processes. A user chooses a process before asking questions. The text API receives only the selected HTML's verified textual evidence, never image pixels. It must cite that evidence or abstain.

A valid citation proves that a quotation exists in the selected source; it does **not** prove that the answer logically follows from it. OCR confidence is not a probability of truth. Source documents themselves may be wrong. These distinctions are essential when describing the application to clients.

## Architecture and responsibilities

```text
PDF path
  → PyMuPDF native text + embedded raster images
  → local Tesseract → OCR lines, word scores and image coordinates
  → native heading boundaries / legacy sections
  → source.html → integrity-checked text
  → deterministic heading ownership OR legacy API classification
  → process HTML files + withheld evidence + manifest
  → selected process HTML → verified evidence batches → text API
  → schema checks → scoped exact citations → answer or abstention
  → original cited screenshot displayed locally
```

`cli.py` manages prompts, options, disclosure, terminal rendering and process selection. `ocr.py` runs Tesseract and parses its TSV output. `pipeline.py` owns extraction, segmentation, provider requests, HTML export/verification, classification and chat. `requirements.txt` pins Python dependencies. `test_pipeline.py` contains offline regression tests; it does not establish model accuracy. The documentation website includes source snapshots for inspecting exact implementation details.

## Installation and first run

Use a supported Python environment compatible with the pinned dependencies. Create a virtual environment and install `requirements.txt`. Install Tesseract separately: it is a system executable, not a pip package. On macOS use `brew install tesseract`; on Debian/Ubuntu install `tesseract-ocr` and the required language packages. For other platforms use the official Tesseract installation documentation. The default language is `eng`; additional languages require their traineddata files.

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python cli.py --pdf '/path/to/document.pdf' --layout headers
```

Dragging a PDF into the terminal supplies its path; typing the path also works. The preview is local PDF metadata and extracted text, not an LLM summary. The system PDF viewer is optional. OCR availability is checked before provider configuration.

For local extraction and heading-based HTML export without API calls:

```sh
python cli.py --pdf '/path/to/document.pdf' --layout headers --extract-only
```

Use `--ocr off` only deliberately: screenshots then remain visible but their contents are unavailable to the text model. Direct Python callers of `extract()` must pass an OCR engine; its library default is no OCR.

## Packages and engine choice

PyMuPDF reads PDF text, font sizes, bounding boxes and images, and normalizes images to PNG. `requests` performs HTTP requests. `jsonschema` validates provider outputs. `rich` renders the CLI. Standard-library HTML parsing, hashing, temporary files, CSV, JSON and subprocess support keep the implementation small. See the repository requirements for exact package pins.

Tesseract runs locally with OEM 1, its LSTM recognition engine. This is neural OCR, **not** an LLM or SLM. No text-generation model repairs OCR results. Its TSV output supplies word scores and coordinates used by the application’s conservative filtering.

Rust's `ocrs` is a plausible future backend, also using neural recognition rather than an LLM. Its project currently describes an early preview and Latin-alphabet support. The inspected CLI JSON exports text and geometry but no word-confidence fields equivalent to this implementation’s input. Replacing Tesseract would therefore require a deliberately revised uncertainty policy, model distribution and equivalent provenance support. Rust alone does not prove faster or more robust recognition; no comparative benchmark was performed on these PDFs. Tesseract is retained for this release.

References: [ocrs project](https://github.com/robertknight/ocrs), [ocrs CLI output implementation](https://github.com/robertknight/ocrs/blob/main/ocrs-cli/src/output.rs), [Tesseract quality guidance](https://tesseract-ocr.github.io/tessdoc/ImproveQuality.html), [Tesseract command usage](https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html).

## Configuration reference

| Option | Meaning / default |
| --- | --- |
| `--pdf` | One PDF path; interactive path prompt when omitted |
| `--layout auto` | Use heading layout if recognized native process headings exist; otherwise legacy segmentation |
| `--layout headers` | Require recognized native process headings; fail if none are found |
| `--layout legacy` | Use legacy evidence sections / page-based model classification |
| `--header-pattern` | Full-match regular expression with named `(?P<process>...)` capture |
| `--ocr on` | Default; local OCR of extracted raster images |
| `--ocr-language eng` | Installed language code, or combination such as `eng+deu` |
| `--ocr-psm 6` | Segmentation mode; alternatives 3 and 11 |
| `--ocr-min-confidence 60` | Minimum score for every word in an eligible line |
| `--ocr-timeout 45` | Per-image timeout; accepted range 1–300 seconds |
| `--tesseract tesseract` | Executable name or explicit executable path |
| `--tessdata-dir` | Optional explicit language-data directory |
| `--context-chars 24000` | Character budget, not token count; minimum 4000 |
| `--payload` | Optional fixed-target JSON; otherwise discover identities |
| `--auth` | `bearer` or `api-key` |
| `--url-type` | `auto`, `base`, or `chat` for a full custom completion URL |
| `--response-format` | `json_object` or `json_schema` |
| `--extract-only` | Local extraction/export; no provider calls |
| `--no-browser` | Exit after export instead of entering the interactive process browser |

For example, `--header-pattern '^Process name: (?P<process>[A-Za-z0-9_.-]+)$'` recognizes that exact native heading convention. A broad expression can incorrectly interpret a log line as a heading; configure it for the actual document format.

## Extraction and provenance

Each input PDF has a SHA-256 digest. Each page, native text line, image and OCR line has a stable source-derived identifier. Named page slices preserve their original page numbers and validate filename page-count claims. Native lines retain font spans and PDF coordinates. PNG images retain source-page coordinates, byte counts and SHA-256 hashes. OCR lines reference their parent image and include pixel-coordinate boxes, word text, word scores, minimum score, mean score and eligibility.

The original normalized PNG is retained. OCR works on a temporary copy: flatten transparency against white, convert to grayscale, and invert predominantly dark images. This is a heuristic for screenshots, not a universal image enhancement algorithm. No identifier spelling, timestamp or missing word is guessed.

Tesseract runs without a shell and with a per-image timeout. Languages and executable availability are checked first. Images above 25 megapixels and TSV output above 8 MB are rejected. These checks occur after relevant decoding or output generation; they are not a complete memory/disk sandbox. Invalid TSV coordinates or nonfinite scores fail extraction. Engine errors and timeouts do not silently become empty successful evidence.

An empty result is recorded as unreadable/no text. A line is eligible only if **every word** meets the threshold and it contains no prohibited invisible control/format characters. A single low-score “not” therefore withholds the entire line. All original lines remain visible for local inspection. Withheld lines enter model context only as an explicit unavailable-text placeholder and cannot be cited.

A bounded in-memory LRU cache reuses results for byte-identical PNGs within one engine instance: at most 32 images and approximately 8 MB of serialized results. Each occurrence still has its own provenance. Repeated screenshots are not independent corroboration. There is no persistent cross-run cache or automatic model download.

## Native heading ownership

`process_header()` accepts only native PDF text, not OCR text. Default conventions include explicit Process/Service/Runtime labels at sufficient font size and larger standalone identifiers containing a hyphen, underscore or dot. The custom pattern replaces default recognition when supplied. These are document-layout heuristics, not a universal semantic heading detector.

`segment_headers()` keeps a recognized process active across contiguous pages until a different process heading appears. Repeating the same heading does not reset its context. Material before the first heading is withheld. Page-family changes or page gaps reset ownership. A raster image whose bounding box intersects a recognized heading is withheld together with its OCR lines, because it may span an ownership boundary. This conservative geometry check does not detect every possible mixed-content image.

Opening native text before the first image becomes header context. These anchors, including any native alias map, accompany later chat batches. Consequently a map on the first page need not disappear when a later screenshot is queried. Maps embedded only in earlier screenshots do not receive this special repetition; cross-batch alias questions may remain unresolved.

Header ownership is deterministic: screenshot text cannot refile a section under a server mentioned in a log. Confidence 1 on this route means certainty about the chosen heading boundary, **not** certainty about the event or OCR. Exact repeated labels aggregate into one exported process. Case differences and similar identifiers remain distinct.

## Legacy classification

Legacy segmentation recognizes existing evidence start/close markers and records interrupted or ambiguous boundaries. If no such markers exist, sections default to pages. The API discovers an exact process/entity label from text, or chooses among supplied fixed targets. It may return uncertain, mixed or unmatched evidence. Start and stop records should share the same identity.

Code verifies section identity, status/target consistency, supplied-target membership, and that a newly discovered label occurs exactly in usable evidence with identifier boundaries. It does not permit invented names. Model confidence is an estimate and is not an accuracy guarantee or a calibrated routing threshold. Heading-led client PDFs should normally use `--layout headers` to avoid accidental legacy fallback.

## Migration and hallucination edge cases

| Case | Intended treatment | Mechanism and limit |
| --- | --- | --- |
| One heading, many image-only continuation pages | Keep all under the heading | Deterministic active-heading ownership |
| Server A → server B | Record host placement separately from process ownership | Ownership enforced in code; event meaning interpreted by model |
| Process A → process B | Resolve roles only from an explicit same-section map | Repeated native anchors + prompt rule; missing map remains unknown |
| Header names source process A | Do not assume header is destination B | Role-sensitive prompt instruction |
| Reverse process B → A | Preserve direction | Model reasoning; no deterministic event parser |
| Server 2 versus server 20 | Keep identities distinct | Exact label checks and instructions |
| Same aliases reused in another group | Do not borrow that group's mapping | Selected-process isolation; local-context instruction |
| Approved/planned/dry-run transfer | Do not claim execution | Semantic prompt rule |
| Partial migration or copied files | Do not claim full service migration | Semantic prompt rule |
| Successful move followed by rollback | Respect chronology and later evidence | Semantic prompt rule; no global cross-batch reconciliation |
| Start evidence without stop evidence | Answer supported part, state missing part | Multipart-answer instruction |
| Conflicting same-time collectors | Report unresolved conflict / abstain | Prompt rule, not a contradiction solver |
| Uploaded later, captured earlier | Use event/capture time appropriately | Prompt rule; unknown timezones not invented |
| Redacted destination or absent alias map | Preserve unknowns | Prompt rule and abstention route |
| “Ignore instructions” inside a log | Treat as evidence, never an instruction | Prompt separation; not a proof against all injection |
| OCR reads O/0 or I/l/1 incorrectly | Do not silently normalize identifiers | No correction code; confidence gate cannot catch every error |
| Duplicate screenshot | Do not count as two confirmations | Cache/hash metadata and model instruction |
| Image intersects a heading | Withhold image and its OCR | Deterministic geometry quarantine |
| Quote drops “not” from OCR line | Reject shortened OCR quote | Full-line OCR citation equality |
| Low-confidence or invisible-control OCR | Retain locally, exclude usable text | Deterministic line gate |
| Edited HTML or replaced screenshot | Stop before using inconsistent evidence | Provenance checks and image hashes |

“Process B is the process named by this header” is accepted only if the document supplies that relationship. A heading alone identifies the owner of the section, not all roles mentioned within its images. This avoids tailoring logic to any synthetic example.

## HTML integrity and exported artifacts

`source.html` is generated before classification. Export writes process HTML, withheld evidence, manifest and image references. HTML escapes source text and embeds PNG images. OCR transcripts are visible beneath the page with provenance labels. The manifest records source hashes, extraction settings and routing decisions; no API secret is stored.

`read_html()` reads actual exported HTML and verifies expected IDs, section ownership, page references, exact text and OCR metadata against extraction provenance. Missing, duplicated, foreign or edited evidence fails instead of falling back to another process. For newly extracted images, embedded PNG encoding and digest are checked. Local PNGs are also checked when exporting or displaying a cited reference.

Hashes detect changes relative to this run’s in-memory baseline. They do not authenticate a client document, prove its events happened, or protect against someone changing the baseline and artifacts together. Older manually constructed provenance without image hashes does not gain new image verification retroactively. Export is not transactional; an interrupted run can leave partial output. Do not treat an incomplete run as a completed report.

## Chat evidence and context budgets

The user selects a process, optionally a section, then asks a question. Its HTML is verified before any filtering. Histories are separate per process and selected section; recent conversation is not evidence. At most four turns are retained and history receives only a bounded share of the budget.

The packer visits every selected evidence unit and creates bounded batches instead of truncating evidence silently. Native header anchors repeat where needed. The budget includes serialized request structure and reserves space for repair feedback; it is a character heuristic, not a provider token guarantee. A single oversized line or opening context causes an actionable error. Increase the budget only within the provider's actual context capacity, shorten the question, or clear history.

Answers from multiple batches are explicitly labelled. There is **no global event timeline or final cross-batch synthesis**. A later rollback in a different batch can therefore require human reconciliation. The notice warns that no cross-batch current-state conclusion has been verified. This is a material limitation, not evidence of full-document semantic consistency.

## Guardrails enforced by code

1. OCR eligibility uses minimum word confidence and invisible-control rejection; excluded text is not citeable.
2. Native heading ownership and orphan/cross-heading quarantine prevent screenshot mentions from changing owners.
3. HTML identity, text, metadata and image checks fail closed on inconsistencies.
4. Provider JSON must satisfy the expected schema; duplicate keys, nonfinite values and unsafe decoded controls are rejected. Invalid structure receives one bounded repair attempt.
5. A non-abstaining answer must be nonempty and have citations. Each citation must reference a current selected evidence line, its correct section and page, and a nonempty verbatim quotation.
6. OCR quotations must equal the entire OCR line, preserving adjacent negation. Native text quotations may be exact substrings.
7. A legacy parent-block ID is normalized only when exactly one supplied line matches; ambiguity is rejected.
8. Citation failure receives one repair attempt. A still-invalid batch causes the whole question to abstain rather than returning partial success.
9. Original cited OCR images are resolved through verified parent IDs and hashes. Native-text citations may use page-level image references, which are less precise.

These checks constrain structure and provenance. They do not implement semantic entailment, deterministic alias reasoning, universal injection prevention, or a proof that every claim has supporting evidence. A model can quote a valid line and still misinterpret it. Full-line OCR quotations reduce selective quoting but cannot recover words the OCR engine omitted entirely.

## Provider connection and data disclosure

The supported protocol is OpenAI-compatible Chat Completions. Custom base URLs and full completion routes are supported; this does not imply native Anthropic/Gemini protocol compatibility. HTTPS is required except explicit loopback HTTP. Credentials in URLs, inappropriate query secrets, fragments and redirects are rejected. Authentication supports Bearer or api-key headers.

Keys are entered hidden and kept in memory. The user approves disclosure before network activity. Native document text, eligible OCR text, labels, questions and selected-process history can reach the configured provider and its upstream services. Image pixels stay local. Temperature is 0 and response length is bounded, but deterministic model behavior is not guaranteed.

Requests have connection/read timeouts; there is no general automatic network retry. Schema repair and citation repair can together cause up to four completion requests per evidence batch. There is no document-wide spending cap or total wall-clock deadline. Provider errors are reported without exposing response bodies or tokens.

## Operations and troubleshooting

**Missing Tesseract/language:** install the executable and traineddata, verify PATH or supply explicit flags. Do not quietly disable OCR when screenshot contents are required.

**Wrong ownership:** inspect the native headings in source HTML. Prefer `--layout headers`, tighten the custom full-match pattern, and check font/layout conventions. Do not fix it by hardcoding a particular server name.

**Abstained answer:** inspect `/evidence` and `/images`. Determine whether the relevant line is absent, low-confidence, in another process, lacks an alias mapping, or conflicts with other evidence. Check full OCR lines against the image, including “not”, timestamps and direction. Lowering confidence simply admits more uncertain text; it does not improve OCR.

**OCR text poorly recognized:** supply a clearer PDF or try an appropriate PSM and installed language. Current preprocessing does not deskew, rotate, detect handwriting or reconstruct tables semantically. Preserve the original and review changes before trusting results.

**Context error:** clear history, shorten the question or increase `--context-chars` responsibly. For multi-batch answers, inspect all batches before making a current-state claim.

**Citation rejection:** verify the model supports the structured response mode. OCR citations require complete single lines. Do not bypass validation to make an answer appear successful.

**HTML/image mismatch:** regenerate from the original PDF; do not disable integrity checks. The application is designed around current-run provenance, not arbitrary edited HTML or an unvalidated resume workflow.

**Terminal cannot display images:** terminal protocol support varies; use the exported HTML or system viewer. A text-only model cannot independently inspect the original screenshot.

## Limitations and planned improvements

Scanned headings are not trusted ownership boundaries. The application extracts embedded raster images; it does not OCR an entire rendered page or vector-only drawings. Multi-column reading order, tables, rotated text, decorative headings, headings without supported naming conventions and images containing multiple processes can be ambiguous. The automatic layout mode may select the wrong strategy. Missing pages not reflected in supplied numbering cannot be discovered automatically.

Confidence filtering may reject correct text and accept incorrect text. Low-quality negation, handwritten text, aliases inside prior screenshot batches, uncertain timezones and conflicting event records remain difficult. Current semantic safeguards are prompt instructions plus provenance validation, not a rules-based event engine.

Future work should be explicitly scoped: reviewed scanned-header detection; typed event records with evidence citations; an alias graph scoped by section and time; deterministic chronology/rollback reconciliation; per-claim entailment review; an OCR adapter with equivalent provenance; controlled fixture evaluation; resource isolation and transactional export. None of these should be described as already implemented.

## Maintenance and handover

Keep extraction provenance and exported HTML in sync when changing data fields. Update `read_html()` whenever export markup or OCR metadata changes. Preserve exact source text and parent image links. Add new layout conventions through the heading detector or explicit pattern, not client-name constants. Keep semantic prompt changes separate from enforceable validation so reviewers know what is guaranteed.

Before a production release, an operator should run offline regression tests and inspect representative client documents, including low-quality scans, aliases, negation, partial transfers and rollbacks. Use fake providers for deterministic validation tests and a separately approved, budgeted model evaluation for answer quality. This update does not claim that these evaluations were performed.

The published `documentation.html` is a standalone static page; `index.html` points to it for GitHub Pages. Keep this handbook, the website and source snapshots aligned when publishing. `ARCHITECTURE_NOTES.md` provides the shorter handwritten study version. The older documentation archive is historical and does not describe this release.
