"""Interactive terminal frontend. Run `python cli.py --help` for local-only options."""
from __future__ import annotations

import argparse
import base64
from datetime import datetime
from getpass import getpass
import os
import re
from pathlib import Path
import shlex
import subprocess
import tempfile
import sys
import time

import pymupdf

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn, TimeElapsedColumn
from rich.table import Table

from pipeline import (Chat, Client, PipelineError, classify, export, extract, image_for_process,
                      load_targets, selected_sections, validate_pdf, discovered_targets)

CONSOLE = Console(markup=False, highlight=False)


def safe(text):
    """Prevent source evidence or model text from injecting terminal control sequences."""
    return ''.join(c for c in str(text) if c in '\n\t' or (ord(c) >= 32 and ord(c) != 127))


def say(text):
    """Print untrusted text literally, including square brackets."""
    CONSOLE.print(safe(text))


def prompt(label, default=''):
    """Read a visible value with an optional default; Ctrl-C cancels safely."""
    result = input(f'{label}' + (f' [{default}]' if default else '') + ': ').strip()
    return result or default


def pdf_path(value: str) -> Path:
    """Resolve typed, quoted or shell-escaped drag-and-drop paths without a shell."""
    value = value.strip()
    if not value:
        raise PipelineError('Enter a PDF path.')
    # Try literal paths first so real quotes/backslashes in filenames are preserved.
    literal = Path(value).expanduser()
    if literal.is_file():
        return validate_pdf(literal)
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        unquoted = Path(value[1:-1]).expanduser()
        if unquoted.is_file():
            return validate_pdf(unquoted)
    if os.name != 'nt':
        try:
            parts = shlex.split(value)
        except ValueError:
            raise PipelineError('The path has unmatched quotes. Drag the PDF again or type its full path.') from None
        if len(parts) == 1:
            return validate_pdf(Path(parts[0]))
    raise PipelineError('Choose one existing PDF file. Drag it into the terminal or type its path.')


def select_pdf(value=None):
    """Validate a command-line path or let an interactive user correct their input."""
    if value is not None:
        return pdf_path(value)
    while True:
        try:
            return pdf_path(prompt('Drag and drop a PDF here, or type its path'))
        except PipelineError as error:
            say(f'Error: {error}')


def image_protocol():
    """Select a native graphics protocol, with an override for unrecognized terminals."""
    if not sys.stdout.isatty():
        return None
    override = os.environ.get('EVIDENCE_IMAGE_PROTOCOL', 'auto').lower()
    if override in ('kitty', 'iterm2'):
        return override
    if override == 'none' or os.environ.get('TMUX') or os.environ.get('STY'):
        return None
    terminal = os.environ.get('TERM', '').lower()
    program = os.environ.get('TERM_PROGRAM', '').lower()
    if ('kitty' in terminal or 'ghostty' in terminal or program in ('kitty', 'ghostty') or
            os.environ.get('KITTY_WINDOW_ID')):
        return 'kitty'
    if program in ('iterm.app', 'wezterm') or os.environ.get('WEZTERM_PANE'):
        return 'iterm2'
    return None


def supports_images():
    """Report whether the current output supports a detected native image protocol."""
    return image_protocol() is not None


def preview_pdf(source: Path):
    """Show local PDF details and a first-page preview before collecting credentials."""
    try:
        with pymupdf.open(source) as document:
            if document.needs_pass:
                raise PipelineError('Encrypted PDF: provide an unlocked local copy.')
            if not document.is_pdf or not len(document):
                raise PipelineError('Choose a PDF containing at least one page.')
            page = document[0]
            say(f'\nPDF preview: {source.name}\nLocation: {source.resolve()}\n'
                f'Pages: {len(document)} | Size: {source.stat().st_size / 1024:.1f} KB')
            text = page.get_text(sort=True).strip()
            say('First-page text excerpt (local extraction, up to 800 characters):')
            say(text[:800] + ('\n[Preview shortened]' if len(text) > 800 else '')
                if text else 'No extractable text on the first page.')
            if supports_images():
                # Preview pixels remain local and temporary, never part of LLM context.
                with tempfile.TemporaryDirectory(prefix='pdf-preview-') as folder:
                    image = Path(folder) / 'first-page.png'
                    scale = min(1.0, 900 / max(page.rect.width, page.rect.height))
                    page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False).save(image)
                    show_image(image)
            else:
                say('This terminal cannot show a visual PDF preview inline.')
                if sys.stdin.isatty() and prompt('Open the PDF in the system viewer for a visual preview? [y/N]', 'n').lower() == 'y':
                    open_local(source)
    except (OSError, RuntimeError, ValueError):
        raise PipelineError('Cannot preview this PDF. Check that it is readable and not damaged.') from None


def configure(auth='bearer', mode='json_object', endpoint_kind='auto'):
    """Collect an in-memory key, exact model ID and explicit disclosure consent."""
    endpoint = prompt('API base URL or full chat-completion URL (HTTPS)')
    if not sys.stdin.isatty():
        raise PipelineError('Use an interactive terminal for hidden API-key entry, or run --extract-only.')
    key = getpass('API key or token (hidden; never saved): ')
    model = prompt('Model ID, or Enter for router auto-selection (/models lists models)', 'auto')
    say('Classification and chat send evidence to the configured API, which may forward to upstream providers: '
        'extracted document text and selected-group conversation text. Images stay local.')
    if prompt('Approve this disclosure to the configured service? Type YES') != 'YES':
        raise PipelineError('Disclosure not approved. Use --extract-only to inspect local conversion.')
    client = Client(endpoint, key, model, mode=mode, consent=True, endpoint_kind=endpoint_kind, auth=auth)
    if model == '/models':
        with CONSOLE.status('Loading model catalog…'):
            catalog = client.models()
        if not catalog:
            raise PipelineError('No callable models listed. Check provider access/quota or enter an exact model ID.')
        for number, name in enumerate(catalog, 1):
            say(f'{number}. {name}')
        selection = prompt('Exact model ID from this catalog')
        if selection not in catalog:
            raise PipelineError('Select an exact listed model ID.')
        client.model = selection
    elif model in ('auto', '/auto'):
        client.model = 'auto'
        say('Service auto routing selected explicitly; this requires support from the configured API.')
    elif not model:
        raise PipelineError('Enter an exact model ID or explicitly choose /auto.')
    say(f'Configured model route: {client.model}')
    return client


def stage(label, function):
    """Show real completed-unit counts and elapsed time, plus an indeterminate spinner."""
    with Progress(SpinnerColumn(), TextColumn('{task.description}'), BarColumn(),
                  MofNCompleteColumn(), TimeElapsedColumn(), console=CONSOLE) as progress:
        task = progress.add_task(label, total=None)

        def update(done, total):
            """Advance only after the backend completes a page or section."""
            progress.update(task, completed=done, total=total)

        return function(update)


def results(data, decisions):
    """Show every decision with original pages and an uncalibrated confidence estimate."""
    table = Table(title='Routing results — confidence is a model estimate')
    for heading in ('Section', 'Pages', 'Process', 'Status', 'Confidence', 'Reason'):
        table.add_column(heading, overflow='fold')
    sections = {s['id']: s for s in data['sections']}
    for d in decisions:
        pages = sorted({b['page'] for b in sections[d['section_id']]['blocks']})
        table.add_row(d['section_id'], ','.join(map(str, pages)), safe(d['target'] or '—'),
                      d['status'], f'{d["confidence"]:.2f}', safe(d['reason']))
    CONSOLE.print(table)


def evidence(sections):
    """Print complete source text and image references with section/block/page citations."""
    for number, section in enumerate(sections, 1):
        say(f'\nChunk {number}: {section["id"]}')
        for b in section['blocks']:
            say(f'  [{b["id"]}, source page {b["page"]}] {b["text"] if b["kind"] == "text" else "LOCAL IMAGE"}')


def show_image(path: Path, offer_viewer=True):
    """Display locally through Kitty/iTerm2; otherwise offer a default-viewer fallback."""
    if not path.is_file():
        raise PipelineError('Image file is missing. Reconvert the source PDF.')
    protocol = image_protocol()
    if protocol == 'kitty':
        encoded = base64.b64encode(path.read_bytes()).decode()
        for start in range(0, len(encoded), 4096):
            chunk = encoded[start:start + 4096]
            more = int(start + 4096 < len(encoded))
            control = f'a=T,f=100,q=2,m={more}' if start == 0 else f'm={more}'
            sys.stdout.write(f'\033_G{control};{chunk}\033\\')
        sys.stdout.flush()
    elif protocol == 'iterm2':
        encoded = base64.b64encode(path.read_bytes()).decode()
        sys.stdout.write(f'\033]1337;File=inline=1;preserveAspectRatio=1:{encoded}\a\n')
        sys.stdout.flush()
    else:
        say(f'Inline image display is unavailable in this terminal. Local image: {path}')
        say('Use Ghostty, Kitty, iTerm2 or WezTerm for native inline images.')
        if offer_viewer and sys.stdin.isatty() and prompt('Open in the system image viewer? [y/N]', 'n').lower() == 'y':
            open_local(path)


def open_local(path):
    """Open one existing local file without a shell or any LLM call."""
    if not path.is_file():
        raise PipelineError('The selected local file is missing.')
    if sys.platform == 'darwin':
        command = ['open', str(path.resolve())]
    elif sys.platform == 'win32':
        os.startfile(path.resolve())
        return
    else:
        command = ['xdg-open', str(path.resolve())]
    try:
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError):
        raise PipelineError('Cannot launch the default viewer. Open the displayed local path manually.') from None


def images(data, decisions, target, run, selection=None):
    """Choose a reference by number or ID and display it without calling the LLM."""
    references = []
    for section in selected_sections(data, decisions, target):
        for index, block in enumerate(section['blocks']):
            if block['kind'] == 'image':
                caption = next((b['text'] for b in section['blocks'][index + 1:]
                                if b['kind'] == 'text'), '(no following caption)')
                references.append(block)
                say(f'{len(references)}. {block["id"]} | page {block["page"]} | {caption}')
    if not references:
        say('No image references in this selection.')
        return
    selection = selection or prompt('Image number or ID (blank to return)')
    if selection:
        if selection.isdigit():
            number = int(selection)
            if not 1 <= number <= len(references):
                raise PipelineError('Choose a listed image number.')
            selection = references[number - 1]['id']
        show_image(image_for_process(data, decisions, target, selection, run))


def answer_images(data, decisions, target, run, answer):
    """Display source images attached to cited sections, scoped to the current group."""
    cited = {c['section_id'] for c in answer['citations']}
    for section in selected_sections(data, decisions, target):
        if section['id'] not in cited:
            continue
        for block in section['blocks']:
            if block['kind'] == 'image':
                say(f'Reference image: source page {block["page"]} | {block["id"]}')
                show_image(image_for_process(data, decisions, target, block['id'], run), offer_viewer=False)


def list_process_html(manifest, run):
    """Provide a portable /ls view of every target HTML and its routing status."""
    say(f'Process HTML files — run status: {manifest["state"]}')
    if not manifest['documents']:
        say('No groups assigned yet. Inspect withheld.html for unclassified evidence.')
    for target, name in manifest['documents'].items():
        path = run / name
        count = sum(d['status'] == 'assigned' and d['target'] == target for d in manifest['decisions'])
        detail = f'{path.stat().st_size:,} bytes' if path.is_file() else 'MISSING'
        say(f'{name} | {target} | {count} assigned sections | {detail} | {path.resolve()}')


def browse(data, decisions, targets, manifest, run, client):
    """Expose every process and withheld document, plus isolated process chat commands."""
    chat = Chat(data, decisions, client, run, manifest['documents']) if client else None
    while True:
        say('\nDocuments:')
        for number, target in enumerate(targets, 1):
            count = len(selected_sections(data, decisions, target))
            say(f'{number}. {target} ({count} sections) — {run / manifest["documents"][target]}')
        say('w. Withheld evidence   r. Results   /ls. List HTML files   i. Open index   q. Quit')
        choice = prompt('Select document')
        if choice in ('q', '/quit'):
            return
        if choice == '/ls':
            list_process_html(manifest, run)
            continue
        if choice == 'r':
            results(data, decisions)
            continue
        if choice == 'i':
            open_local(run / 'index.html')
            continue
        if choice == 'w':
            target = None
        elif choice in targets:
            target = choice
        elif choice.isdigit() and 1 <= int(choice) <= len(targets):
            target = targets[int(choice) - 1]
        else:
            say('Choose a listed document number or command.')
            continue
        chunk = None
        say(f'\nSelected: {target or "Withheld evidence"}. /help lists commands.')
        while True:
            command = prompt('Question or command')
            try:
                if command in ('/back', '/process'):
                    break
                if command == '/quit':
                    return
                if command == '/help':
                    say('/ls: list process HTML files | /evidence: source text and chunk IDs | /images [number]: local images | /html: open document\n'
                        '/chunk N: explicitly limit chat to one section | /all: full process | /clear: reset this chat history\n'
                        '/process or /back: switch documents | /quit: exit')
                elif command == '/ls':
                    list_process_html(manifest, run)
                elif command == '/evidence':
                    evidence(selected_sections(data, decisions, target))
                elif command == '/images' or command.startswith('/images ') or re.fullmatch(
                        r'(?:show|display)(?: me)?(?: the)?(?: reference| evidence)? (?:images?|screenshots?)(?: please)?', command, re.I):
                    selection = command.split(maxsplit=1)[1] if command.startswith('/images ') else None
                    images(data, decisions, target, run, selection)
                elif command == '/html':
                    open_local(run / (manifest['documents'][target] if target else 'withheld.html'))
                elif command.startswith('/chunk '):
                    number = command.split(maxsplit=1)[1]
                    if not number.isdigit() or not 1 <= int(number) <= len(selected_sections(data, decisions, target)):
                        raise PipelineError('Use /evidence to see valid chunk numbers, then /chunk N.')
                    chunk = int(number)
                    say(f'Chat now covers ONLY section chunk {chunk}; other sections are excluded explicitly.')
                elif command == '/all':
                    chunk = None
                    say('Chat now covers the full selected process.')
                elif command == '/clear':
                    if chat:
                        chat.histories.pop((target, chunk), None)
                    say('Selected chat history cleared.')
                elif command.startswith('/'):
                    say('Unknown command. Use /help.')
                elif command:
                    if target is None or chat is None:
                        say('Chat requires a classified process and an approved model connection.')
                        continue
                    with CONSOLE.status('Waiting for a cited text answer…'):
                        answer = chat.ask(target, command, chunk)
                    if chat.last_notice:
                        say(chat.last_notice.strip())
                    say(answer['answer'])
                    for citation in answer['citations']:
                        say(f'{citation["section_id"]} / {citation["block_id"]}, source page {citation["page"]}: "{citation["quote"]}"')
                    answer_images(data, decisions, target, run, answer)
            except PipelineError as error:
                say(f'Error: {error}')


def main():
    """Run the workflow; preserve a local review export before any network classification."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pdf', help='Path to one PDF file (or enter/drag it at the prompt)')
    parser.add_argument('--payload', type=Path, help='Optional fixed target labels; otherwise the LLM discovers groups')
    parser.add_argument('--auth', choices=['bearer', 'api-key'], default='bearer', help='Advanced: authentication header')
    parser.add_argument('--response-format', choices=['json_object', 'json_schema'], default='json_object', help='Advanced: provider JSON mode')
    parser.add_argument('--url-type', choices=['auto', 'base', 'chat'], default='auto', help='Advanced: API URL interpretation')
    parser.add_argument('--context-chars', type=int, default=24000, help='Serialized request character budget (not tokens)')
    parser.add_argument('--extract-only', action='store_true', help='Convert and export locally; never configure or call a model')
    parser.add_argument('--no-browser', action='store_true', help='Exit after writing output files')
    args = parser.parse_args()
    if args.context_chars < 4000:
        raise PipelineError('--context-chars must be at least 4000.')
    say('Evidence Splitter\nChoose PDF → preview → configure text model → convert → discover groups → inspect → chat/view images')
    start = time.monotonic()
    source = select_pdf(args.pdf)
    preview_pdf(source)
    targets = load_targets(args.payload.expanduser()) if args.payload else None
    client = None if args.extract_only else configure(args.auth, args.response_format, args.url_type)
    if client:
        client.budget = args.context_chars
    say('The LLM will discover process groups from the PDF text.' if targets is None
        else 'Routing to the labels in the supplied payload.')
    run = Path('runs') / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    say(f'Output folder: {run.resolve()}')
    data = stage('Converting pages', lambda progress: extract(source, run, progress))
    say(f'Extracted {len(data["pages"])} pages and {len(data["sections"])} sections.')
    decisions = [dict(section_id=s['id'], status='uncertain', target=None, confidence=0,
                      reason=s['boundary'] or 'Not classified; local extraction only.') for s in data['sections']]
    manifest = export(data, targets or [], decisions, run, state='not classified')
    if client:
        try:
            decisions = stage('Discovering groups' if targets is None else 'Classifying sections', lambda progress: classify(data, targets, client, run, progress))
        except (PipelineError, KeyboardInterrupt):
            say(f'Classification stopped. Local evidence remains available at {run.resolve() / "index.html"}. No partial routing was published.')
            raise
        targets = discovered_targets(decisions) if targets is None else targets
        manifest = export(data, targets, decisions, run)
    results(data, decisions)
    list_process_html(manifest, run)
    say(f'Finished in {time.monotonic() - start:.1f}s. Review: {run.resolve() / "index.html"}')
    if not args.no_browser:
        browse(data, decisions, list(manifest['documents']), manifest, run, client)


if __name__ == '__main__':
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        say('\nCancelled. Any completed local exports remain in runs/.')
    except PipelineError as error:
        say(f'Error: {error}')
        sys.exit(1)
    except Exception:
        # Never emit a traceback that might include provider credentials or content.
        say('Local operation failed. Check the input PDF, output permissions and installed requirements. No provider details were logged.')
        sys.exit(1)
