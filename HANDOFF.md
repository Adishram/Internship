**The Problem** We frequently process 30-40 page PDFs containing mixed evidence for two completely separate processes. To route this data correctly downstream, we need to split this single document into two distinct sets based on specific target values provided in an input payload.

**Your Responsibilities & Workflow** For this project, you will build this pipeline from the ground up, starting with data generation. Here is the step-by-step breakdown of your tasks:

1. **Mock Data Preparation:** Create a realistic mock PDF (roughly 30-40 pages). This document must contain evidence for two distinct processes and include embedded images alongside the text.(we can discuss over a call)
2. **PDF to HTML Conversion:** Research and implement a method to convert this mock PDF into an HTML format. Retaining the structural layout and the embedded images during this conversion is a key part of the challenge.
3. **LLM Classification:** Write logic that takes an input payload (containing your target values) and parses the generated HTML. You will use an LLM to evaluate the content and classify which parts/pages belong to which target value.
4. **HTML Splitting (Final Output):** Based on the LLM's classification, split the content to generate **two separate HTML responses**, each containing only the evidence relevant to its respective process.

**Key Technical Considerations** As you start brainstorming, keep these challenges in mind:

- **Conversion Tools:** What libraries or tools will you use for the PDF-to-HTML conversion to ensure the images and text blocks don't get scrambled?
- **LLM Context Limits:** Passing raw HTML to an LLM can consume tokens very quickly. Think about how to extract the relevant text for the LLM to classify without losing your mapping to the original HTML tags.
- **Accuracy:** The classification needs to be precise so that no evidence ends up in the wrong bucket.

**Next Steps**

1. Review these requirements and brainstorm a high-level approach for each of the four steps.
2. Compile a list of any questions or clarifications you need.
3. Let's plan to meet tomorrow to discuss your initial ideas, the tech stack you want to use, and how you plan to tackle the prompt engineering.

---

# Fresh-start handoff — 13 October 2026

The main prompt above is preserved verbatim. It is the primary project brief. The historical “meet tomorrow” sentence is part of that brief, not a request to schedule a meeting now.

## What to do next

Rebuild this project from scratch in `/Users/adish./Desktop/internship`. The user plans to remove the old implementation and keep the split PDFs and this handoff. Do not assume old source files, environments, generated results, or ZIPs will survive. Do not delete anything on the user's behalf without an explicit request. Start with a small working end-to-end baseline and test it before expanding the interface.

The earlier prototype's overall approach was useful, but **image input to the LLM must be removed**. The new baseline uses a normal text model. Classify using process/service names and surrounding extracted text. Images remain source evidence references that the user can inspect; do not describe image-only contents as if the model had seen them.

## Current implementation requirements

- Python with a simple shared backend and a **custom terminal CLI UI** as the primary frontend. A web UI is not required for this rebuild unless requested later.
- Use PyMuPDF to extract text, raster images, bounding boxes and stable page/block IDs. Preserve these IDs through conversion, classification, exports and Q&A citations.
- Save extracted images as actual files under each run's `images/` directory. Store file paths and provenance in local data structures.
- Retain text layout and images in HTML. Self-contained HTML may embed images as base64 at render/export time; image extraction itself should store files. Never include images, image data URLs, attachments or image-file contents in LLM requests. The model may receive a reference ID and surrounding caption text, but not pixels or machine-specific absolute paths.
- Classify logical evidence sections rather than whole pages: one page can contain multiple unrelated services. Reconstruct continuations across page boundaries using headings and explicit evidence-close markers. Quarantine ambiguous boundaries instead of guessing.
- Extract compact text from the HTML/block mapping for the LLM. Do not send full HTML or base64 assets. Maintain a reversible section-to-block-to-HTML mapping.
- Respect the main prompt's **target values supplied in an input payload**. For the core baseline, accept two process names and route to those exact labels. Support additional targets if straightforward. Let the LLM determine which evidence belongs to each process; service start and stop records belong together, not in separate operation buckets.
- Earlier conversation requested automatic process discovery. It can be an optional mode using text, but must not silently replace the main prompt's payload-driven routing requirement. No requirement to send screenshots for either mode.
- Explicitly handle `uncertain`, `mixed` and `unmatched` sections. Do not duplicate a mixed section into both process outputs. Do not assign screenshot-only sections based on unseen image contents.
- **Do not withhold an otherwise classifiable text section merely because it has an image.** This was a mistake in the earlier vision-dependent design. Associate its image with the surrounding section and preserve it for human review. Mark uncertain when the relevant process identity truly cannot be determined from available text.
- Generate one independent HTML document per target, containing only its assigned source text and associated images. Assemble original evidence; do not ask the model to rewrite or invent evidence. Also export withheld evidence, a decision/provenance manifest and an index linking every process document for manual verification.
- Add process-isolated Q&A. Send only the selected process's classified text and its own conversation history. Cite section/block IDs, original source pages and exact supporting text quotes. Reject fabricated or cross-process citations; abstain when evidence is missing or conflicts. Valid citations do not guarantee that every model paraphrase is correct.
- When a user asks to see evidence images, resolve references locally from the **selected process only** and display them in the terminal. Do not send them to the LLM to make this happen. List image IDs, source pages and captions for selection. Use supported terminal graphics protocols when available; for terminals without image support, explain the limitation and offer the local path/default-viewer fallback. Do not pretend a plain-text terminal displayed an image. A missing image file should produce a clear local error, not trigger an API request.

## Terminal experience

Build an easy-to-use terminal interface with:

1. A clear welcome screen and workflow: choose PDF → configure text model → enter/load target payload → convert → classify → inspect outputs → select process → chat/view evidence.
2. PDF path entry/file selection with validation and sensible defaults.
3. Endpoint, hidden API-key input, optional model name and explicit model auto-selection. Never put API keys in commands, logs, manifests, saved settings or tracebacks.
4. Actual stage progress bars for conversion/classification, section counts, elapsed time and loaders while waiting for network calls. Avoid fabricated percentages during an indeterminate request.
5. A readable results table showing source section/pages, process, status, confidence and reason.
6. A document browser/menu that makes **every classified document** accessible for verification, including sections, text excerpts, images and HTML paths. Withheld evidence must also be inspectable.
7. Separate process chats with commands such as `/process`, `/evidence`, `/images`, `/back`, `/help` and `/quit`, or equally discoverable menus.
8. Friendly actionable errors, cancellation, and useful recovery without exposing credentials or silently dropping evidence.

Suggested minimal stack: Python, PyMuPDF, requests, JSON Schema validation, Rich for tables/progress/spinners, and prompt_toolkit if needed for interactive prompts. A Textual TUI is an option, not a requirement. Keep the baseline simple; no Rust, Laya, RLVR, TOON, database, vector DB or RAG framework.

## Dataset that survives the reset

Existing folder: `/Users/adish./Desktop/internship/split-pdfs/`.

| File | Pages in original PDF | Count |
| --- | --- | --- |
| `Synthetic_Server_Data_pages_01-10.pdf` | 1–10 | 10 |
| `Synthetic_Server_Data_pages_11-20.pdf` | 11–20 | 10 |
| `Synthetic_Server_Data_pages_21-30.pdf` | 21–30 | 10 |
| `Synthetic_Server_Data_pages_31-40.pdf` | 31–40 | 10 |
| `Synthetic_Server_Data_pages_41-50.pdf` | 41–50 | 10 |
| `Synthetic_Server_Data_pages_51-52.pdf` | 51–52 | 2 |

The original synthetic document has 52 pages, rather than the brief's roughly 30–40. These are source-page slices, **not classified process documents**. The user has no ground-truth file. The original was at `/Users/adish./Downloads/Synthetic Server Data.pdf`, but do not depend on that file surviving. Use the split PDFs or reconstruct a combined input locally from them when needed. Preserve original page offsets from the filenames so citations are not mislabeled as pages 1–10 for every slice. Cross-page reconstruction cannot recover missing context if a slice starts halfway through a section; combining the slices avoids that boundary issue.

Previous local extraction found 102 logical evidence sections and 102 embedded images across the full 52-page PDF. This is a historical extraction check, not independently verified classification ground truth. Early pages commonly contain two distinct sections, sometimes for different services on the same server. Examples include `springboot-web`, `catalog-api`, `pricing-api`, `event-dispatcher`, `relay-consumer` and `springboot-relay`. Similar service names must not be merged accidentally.

Reuse the existing synthetic dataset for the baseline. If a strictly 30–40-page/two-process mock is needed to satisfy the original brief separately, make it a clearly labeled additional fixture rather than altering the preserved PDFs. Create a small controlled test fixture with known labels for objective regression testing.

## LLM endpoint and compatibility lessons

The user currently uses **FreeLLMAPI with Groq/Qwen 27B** rather than an OpenAI account. Treat endpoint URLs, exact model IDs and available models as runtime configuration; model versions and availability change.

- FreeLLMAPI is a local router that forwards calls to upstream providers. A localhost URL does not mean the evidence stays local. Obtain explicit approval before sending document text to that configured service.
- Use the user's actual router base URL ending in `/v1`. The documented default is `http://localhost:3001/v1`; a previous UI used `http://127.0.0.1:31415/v1`. Neither is a confirmed current configuration.
- The router expects its **unified key**, not a Groq key in the client. Provider keys are configured in the router.
- For an explicit model, use the exact connected catalog ID, not a display name such as “Qwen 27B.” A published ID observed during development was `qwen/qwen3.8-27b`; verify the user's installed catalog instead of hardcoding this.
- FreeLLMAPI `/models` can list unavailable models. Exclude entries marked `needsKey` or `exhausted` when selecting a callable model. For a FreeLLMAPI-specific profile, blank model can use the router's documented `auto` mode. Keep routing/selected-model behavior visible to the user.
- Structured JSON responses are required and must be validated locally. Offer `json_schema` where supported and explicit `json_object` for compatible providers. Do not silently bypass validation.
- In JSON mode, tell the model to produce a **result instance**, not echo the JSON Schema itself. A single enclosing JSON code fence may be stripped; do not extract convenient-looking JSON from arbitrary prose.
- A single bounded correction attempt for invalid JSON/schema output is reasonable. Preserve exact section IDs and reject unknown/duplicate/missing IDs or inconsistent target/status pairs. Do not silently normalize false IDs, invent evidence or turn every error into a confident assignment.
- Keep errors distinct: network failure, authentication, model/route not found, quota/rate limit, unsupported response envelope, invalid JSON, truncated output and schema violations. Show safe field-level diagnostics without raw provider response text or keys.
- Stop a run on systemic connection/provider errors instead of labeling every section uncertain and consuming repeated quota. Per-section uncertainty about evidence is a separate outcome.
- Reject HTTP redirects for authenticated requests. Prefer HTTPS except for local loopback endpoints.
- Bound text context without silent truncation. If selected-process chat exceeds the budget, explain this and implement an explicit text-only chunking strategy rather than leaking other processes or dropping evidence invisibly.

References for the next implementation to verify when needed:

- PyMuPDF extraction: https://pymupdf.readthedocs.io/en/latest/app1.html
- FreeLLMAPI reference: https://github.com/tashfeenahmed/freellmapi/blob/main/docs/en/api/01-rest-api.md
- Groq models: https://console.groq.com/docs/models

## Lessons to preserve, failures to avoid

The previous prototype had useful extraction, stable provenance, separate process HTML exports, image folders, review indexes and isolated chat. Its tests mostly used mocked LLM responses. **Live provider classification was not verified successful**: the most recent screenshot showed all 20 sections withheld due to a generic transport/validation error. Do not claim the old system achieved accurate routing or inherit its test counts as proof that the fresh code works.

Other prior failures:

- Image-bearing sections were withheld when vision was disabled. Remove that rule for this text-only rebuild.
- A footer heuristic accidentally removed repeated evidence table rows near page bottoms. Preserve tables and audit excluded furniture.
- PDF extraction errors hid folder write-permission failures. Report image-save and PDF-parse failures separately.
- The live web process cached an old backend after changes, causing incompatible constructor errors. This rebuild prioritizes the CLI; use fresh processes and verify the actual execution environment.
- A confidence slider was confusing. Confidence is a model estimate, not calibrated accuracy. Use a sensible documented default/advanced option; do not imply an 0.85 threshold guarantees 85% correct routing.

## Acceptance checks for the new baseline

- An end-to-end controlled fixture with at least two processes produces correct separate HTML documents with original images and layout mapping.
- All classifier and Q&A API request bodies are **text-only**. No image payloads, base64 data URLs or uploaded images reach the model. Inspect requests in tests.
- Viewing an image is a local operation and makes zero LLM calls; a process cannot access another process's image references.
- Images with clear surrounding process text stay attached to their assigned section. Image-only or ambiguous identity evidence is withheld appropriately.
- Mixed-process pages, cross-page continuations, repeated table rows, orphan sections and original page offsets are tested.
- Invalid JSON, wrong section IDs, inconsistent assignments, provider errors and context overflow fail clearly and safely.
- Every process output can be inspected from the CLI; review evidence and decision reasons are accessible.
- Q&A isolates process text and history, checks citations, and abstains on unsupported questions. Test both process switching and foreign image/citation IDs.
- Hidden key input, consent, readable progress/loaders and cancellation work in an actual terminal, not only unit tests.
- Provide requirements, README, example target payload, launch commands and a concise test report distinguishing mock verification from approved live-provider results.
- Never submit confidential evidence to an upstream service during development without approval. If a live test is needed, prepare the concrete request/configuration and obtain approval for that disclosure.

Build the working baseline first. Keep the original main prompt intact in project documentation and treat the sections above as implementation refinements and continuity context.
