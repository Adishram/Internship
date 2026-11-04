# Evidence Splitter

Python CLI for turning a PDF into process-specific HTML evidence, reading embedded screenshots with local Tesseract OCR, and asking a text API questions grounded in a selected process.

## Start

Install Python dependencies from `requirements.txt` in a virtual environment. Install the Tesseract executable and selected language data separately (`brew install tesseract` on macOS; `tesseract-ocr` plus language packages on Debian/Ubuntu).

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python cli.py --pdf '/path/to/document.pdf' --layout headers
```

You can also run `python cli.py` and drag a PDF into the path prompt. Preview text is extracted locally, not summarized by a model. Configure an OpenAI-compatible Chat Completions endpoint, authentication and model; approve disclosure before network activity. Keys remain in memory. Image pixels stay local; eligible OCR text is sent as evidence.

For local OCR and heading-based export without an API:

```sh
python cli.py --pdf '/path/to/document.pdf' --layout headers --extract-only
```

One native process heading owns following pages until the next different heading. Repeated headings retain context. Screenshot mentions of another host do not change ownership. Unowned and cross-heading image evidence is withheld. For other document layouts use `--layout legacy`, or configure `--header-pattern` with a named `process` capture. Scanned headings are not automatic boundaries.

OCR defaults: English, PSM 6, minimum word score 60, timeout 45 seconds. Override with `--ocr-language`, `--ocr-psm`, `--ocr-min-confidence`, `--ocr-timeout`, `--tesseract` and `--tessdata-dir`. `--ocr off` intentionally leaves image contents unavailable to chat.

Select a process to ask questions. Use `/evidence` to inspect text and `/images` for source screenshots. Unsupported or invalidly cited answers abstain. Entire OCR lines must be quoted so negation cannot be dropped from a citation. Exact citations do not guarantee correct interpretation; OCR errors and conflicts across batches still require review.

## Documentation

- [Documentation website](https://adishram.github.io/Internship/)
- `documentation.html`: standalone website with implementation source snapshots.

`cli.py` handles interaction; `ocr.py` handles local recognition; `pipeline.py` handles provenance, ownership, HTML, API validation and chat. The separate Rust application is not required for this Python implementation. Tesseract is retained; no speed comparison with Rust ocrs has been established.
