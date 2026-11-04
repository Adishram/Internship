"""Local Tesseract OCR with line confidence and image-coordinate provenance.

Tesseract's recognition network is an OCR model, not an LLM/SLM. No provider is
called, no generated corrections are applied, and the original PNG is untouched.
Install the Tesseract executable and language data separately from pip packages.
"""
from __future__ import annotations

import csv
from collections import OrderedDict
import copy
import hashlib
import io
import math
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unicodedata

import pymupdf


class OCRError(Exception):
    """An actionable OCR setup or recognition failure, safe to show in the CLI."""


def has_unsafe_controls(text: str) -> bool:
    """Detect invisible formatting/control characters without rewriting evidence."""
    return any(unicodedata.category(c) in ('Cc', 'Cf') and c not in '\n\t' for c in text)


class TesseractOCR:
    """Recognize screenshot lines locally; conservatively gate on worst-word score."""

    def __init__(self, executable='tesseract', language='eng', psm=6,
                 min_confidence=60.0, timeout=45, tessdata=None):
        """Validate options and installed languages before any provider setup."""
        if not re.fullmatch(r'[A-Za-z0-9_]+(?:\+[A-Za-z0-9_]+)*', language):
            raise OCRError('OCR language must be a Tesseract code such as eng or eng+deu.')
        if psm not in (3, 6, 11) or not 0 <= min_confidence <= 100 or not 1 <= timeout <= 300:
            raise OCRError('Use OCR PSM 3, 6 or 11; confidence 0–100; timeout 1–300 seconds.')
        self.executable = shutil.which(str(executable))
        if not self.executable:
            raise OCRError('Tesseract is not installed or not on PATH. Install Tesseract and language data, '
                           'use --tesseract /path/to/executable, or explicitly choose --ocr off.')
        self.language, self.psm = language, psm
        self.min_confidence, self.timeout = min_confidence, timeout
        self.cache = OrderedDict()
        self.cache_bytes = 0
        self.cache_hits = 0
        self.tessdata = Path(tessdata).expanduser().resolve() if tessdata else None
        if self.tessdata and not self.tessdata.is_dir():
            raise OCRError('--tessdata-dir must name an existing language-data directory.')
        command = [self.executable, '--list-langs'] + self.data_arguments()
        try:
            installed = subprocess.run(command, check=True, capture_output=True,
                                       encoding='utf-8', errors='replace', timeout=10)
        except (OSError, subprocess.SubprocessError):
            raise OCRError('Cannot read Tesseract languages. Check its installation and --tessdata-dir.') from None
        languages = set((installed.stdout + '\n' + installed.stderr).splitlines())
        if not set(language.split('+')).issubset({s.strip() for s in languages}):
            raise OCRError('Requested OCR language data is missing. Install the selected traineddata '
                           'or set --tessdata-dir to its directory.')
        try:
            version = subprocess.run([self.executable, '--version'], check=True, capture_output=True,
                                     encoding='utf-8', errors='replace', timeout=10)
            self.version = version.stdout.splitlines()[0][:120]
        except (OSError, subprocess.SubprocessError, IndexError):
            raise OCRError('Cannot read Tesseract version; check its installation.') from None

    def data_arguments(self):
        """Supply an explicit data directory without modifying global environment."""
        return ['--tessdata-dir', str(self.tessdata)] if self.tessdata else []

    def settings(self):
        """Record reproducible non-secret OCR parameters in the run manifest."""
        return dict(engine='tesseract', version=self.version, oem=1, language=self.language, psm=self.psm,
                    minimum_word_confidence=self.min_confidence, timeout_seconds=self.timeout,
                    preprocessing='flatten alpha onto white; grayscale; invert predominantly dark images',
                    max_pixels=25_000_000, cache_hits=self.cache_hits,
                    cache_limits='32 images / 8 MB serialized recognition results')

    def recognize(self, image_path: Path) -> list[dict]:
        """Return OCR lines, word boxes and scores; preserve even rejected lines.

        A timeout or engine failure aborts extraction rather than pretending the
        image was read. An empty OCR result is recorded as unreadable/no text by
        the caller. Confidence is a heuristic score, not a correctness probability.
        """
        try:
            digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
            if digest in self.cache:
                self.cache_hits += 1
                self.cache.move_to_end(digest)
                return copy.deepcopy(self.cache[digest][0])
            pix = pymupdf.Pixmap(str(image_path))
            if pix.width * pix.height > 25_000_000:
                raise OCRError('Image exceeds the 25-megapixel OCR limit. Supply a smaller image/PDF.')
            # Work on a temporary grayscale copy; keep the reference image intact.
            if pix.alpha:
                # Dropping alpha alone retains premultiplied dark pixels. Render
                # against white at native dimensions before grayscale recognition.
                with pymupdf.open() as canvas:
                    page = canvas.new_page(width=pix.width, height=pix.height)
                    page.insert_image(page.rect, pixmap=pix)
                    pix = page.get_pixmap(alpha=False)
            gray = pymupdf.Pixmap(pymupdf.csGRAY, pix)
            samples = gray.samples
            probe = samples[::max(1, len(samples) // 10000)]
            if probe and sum(probe) / len(probe) < 127:
                gray.invert_irect()
            with tempfile.TemporaryDirectory(prefix='evidence-ocr-') as folder:
                image = Path(folder) / 'input.png'
                output = Path(folder) / 'result'
                gray.save(str(image))
                command = [self.executable, str(image), str(output), '-l', self.language,
                           '--oem', '1', '--psm', str(self.psm), *self.data_arguments(), 'tsv']
                subprocess.run(command, check=True, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=self.timeout)
                tsv = output.with_suffix('.tsv')
                if tsv.stat().st_size > 8_000_000:
                    raise OCRError('OCR output exceeds the 8 MB per-image limit. Split the oversized capture.')
                lines = self.parse_tsv(tsv.read_text(encoding='utf-8'), gray.width, gray.height)
                # Reuse only byte-identical images within this configured engine.
                # Each PDF occurrence still receives distinct provenance IDs.
                size = len(repr(lines).encode('utf-8'))
                if size <= 8_000_000:
                    while self.cache and (len(self.cache) >= 32 or self.cache_bytes + size > 8_000_000):
                        _, (_, removed) = self.cache.popitem(last=False)
                        self.cache_bytes -= removed
                    self.cache[digest] = (copy.deepcopy(lines), size)
                    self.cache_bytes += size
                return lines
        except subprocess.TimeoutExpired:
            raise OCRError('OCR timed out. Simplify the image or increase --ocr-timeout (maximum 300).') from None
        except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError):
            raise OCRError('OCR failed. Check the image, Tesseract engine/language data and output permissions.') from None

    def parse_tsv(self, text: str, width: int, height: int) -> list[dict]:
        """Group level-5 TSV words by OCR line, without guessing or repairing text."""
        groups = {}
        reader = csv.DictReader(io.StringIO(text), delimiter='\t', quoting=csv.QUOTE_NONE)
        required = {'level', 'page_num', 'block_num', 'par_num', 'line_num',
                    'left', 'top', 'width', 'height', 'conf', 'text'}
        if not required.issubset(reader.fieldnames or []):
            raise OCRError('Tesseract returned malformed TSV output.')
        try:
            for row in reader:
                if row['level'] != '5' or not row['text'] or not row['text'].strip():
                    continue
                word = row['text']
                confidence = float(row['conf'])
                left, top, w, h = (int(row[k]) for k in ('left', 'top', 'width', 'height'))
                if (not math.isfinite(confidence) or not 0 <= confidence <= 100 or
                        left < 0 or top < 0 or w <= 0 or h <= 0 or
                        left + w > width or top + h > height):
                    raise ValueError('Invalid OCR word metadata')
                key = tuple(row[k] for k in ('page_num', 'block_num', 'par_num', 'line_num'))
                groups.setdefault(key, []).append(dict(text=word, confidence=confidence,
                                                       bbox=[left, top, left + w, top + h]))
        except (TypeError, ValueError, KeyError, csv.Error):
            raise OCRError('Tesseract returned invalid word coordinates or confidence values.') from None
        result = []
        for words in groups.values():
            confidence = min(w['confidence'] for w in words)
            line = ' '.join(w['text'] for w in words)
            unsafe = has_unsafe_controls(line)
            result.append(dict(text=line, words=words,
                               confidence=round(confidence, 3),
                               mean_confidence=round(sum(w['confidence'] for w in words) / len(words), 3),
                               usable=confidence >= self.min_confidence and not unsafe,
                               withheld_reason=('invisible control characters' if unsafe else
                                                'low word confidence' if confidence < self.min_confidence else None),
                               pixel_bbox=[min(w['bbox'][0] for w in words), min(w['bbox'][1] for w in words),
                                           max(w['bbox'][2] for w in words), max(w['bbox'][3] for w in words)]))
        return result
