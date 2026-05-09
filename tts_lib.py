"""
tts_lib — shared TTS rendering + text extraction for the prerender suite
(prerender.py CLI, prerender_gui.py Tkinter GUI, prerender_web.py local web app).

Voice synthesis: Microsoft Edge neural TTS via the edge-tts package.
Free, no API key, very high quality US English voices.

Text extraction supports:
    .txt / .md / .markdown   plain / markdown text
    .docx                    Word documents          (python-docx)
    .pdf                     PDFs                    (pypdf)
    .epub                    ebooks                  (ebooklib + beautifulsoup4)

Each extractor's import is lazy, so a missing optional dependency only
surfaces when the corresponding format is actually used.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import edge_tts


# ============================================================================
# Voices
# ============================================================================

US_VOICES = {
    "aria":        "en-US-AriaNeural",          # warm, conversational female
    "jenny":       "en-US-JennyNeural",         # friendly female
    "guy":         "en-US-GuyNeural",           # natural male
    "ana":         "en-US-AnaNeural",           # younger female
    "christopher": "en-US-ChristopherNeural",   # mature male
    "eric":        "en-US-EricNeural",          # mature male
    "michelle":    "en-US-MichelleNeural",      # mature female
    "roger":       "en-US-RogerNeural",         # mature male
    "steffan":     "en-US-SteffanNeural",       # mature male
}

DEFAULT_VOICE = "en-US-AriaNeural"
DEFAULT_RATE = "-5%"
DEFAULT_PITCH = "+0Hz"


# ---- Latin American Spanish voices ----------------------------------------
# These are Edge TTS neural voices native to Latin American countries (NOT
# es-ES, which is European Spanish). 'dalia' (Mexican female) is the default
# because Mexican Spanish is the most widely-understood LatAm dialect and
# is what international media typically uses for "neutral Latin American".

LATAM_SPANISH_VOICES = {
    "dalia":   "es-MX-DaliaNeural",      # Mexico female (default)
    "jorge":   "es-MX-JorgeNeural",      # Mexico male
    "paloma":  "es-US-PalomaNeural",     # US Spanish female
    "alonso":  "es-US-AlonsoNeural",     # US Spanish male
    "salome":  "es-CO-SalomeNeural",     # Colombia female
    "gonzalo": "es-CO-GonzaloNeural",    # Colombia male
    "camila":  "es-PE-CamilaNeural",     # Peru female
    "alex":    "es-PE-AlexNeural",       # Peru male
    "elena":   "es-AR-ElenaNeural",      # Argentina female
    "tomas":   "es-AR-TomasNeural",      # Argentina male
}

DEFAULT_SPANISH_VOICE = "es-MX-DaliaNeural"


def resolve_voice(name_or_alias: str) -> str:
    """Translate a friendly alias ('aria') to a full voice name. Pass-through
    for any string that isn't a known alias (lets users supply
    'en-GB-RyanNeural' etc. directly). Looks in both the English and Spanish
    catalogs."""
    key = (name_or_alias or "").lower()
    return US_VOICES.get(key) or LATAM_SPANISH_VOICES.get(key) or name_or_alias


# ============================================================================
# File-type buckets
# ============================================================================

PLAIN_EXTS = {".txt", ".md", ".markdown"}
DOCX_EXTS = {".docx"}
PDF_EXTS = {".pdf"}
EPUB_EXTS = {".epub"}
SUPPORTED_TEXT_EXTS = PLAIN_EXTS | DOCX_EXTS | PDF_EXTS | EPUB_EXTS

AUDIO_EXTS = {".mp3", ".m4a", ".wav", ".ogg", ".oga", ".opus", ".flac",
              ".aac", ".webm", ".mp4"}


# ============================================================================
# Text cleanup — strips markdown / source artifacts so the TTS engine reads
# prose, not formatting characters.
# ============================================================================

def strip_markdown(text: str) -> str:
    """Lightweight cleanup so the TTS engine reads prose, not syntax marks."""
    # Fenced code blocks: keep inner text, drop fences
    text = re.sub(r"```[a-zA-Z0-9_+-]*\n([\s\S]*?)```", r"\1", text)
    # Inline code
    text = re.sub(r"`([^`]+)`", r"\1", text)
    # Images: keep alt text only
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    # Links: keep visible text only
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # Headings
    text = re.sub(r"^\s{0,3}#{1,6}\s+", "", text, flags=re.MULTILINE)
    # Bold / italic
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"(?<![A-Za-z0-9])_([^_]+)_(?![A-Za-z0-9])", r"\1", text)
    # List markers
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.MULTILINE)
    # Blockquotes
    text = re.sub(r"^\s*>\s?", "", text, flags=re.MULTILINE)
    # Horizontal rules
    text = re.sub(r"^\s*[-*_]{3,}\s*$\n?", "", text, flags=re.MULTILINE)
    # Leading timestamps like [00:01:23]
    text = re.sub(
        r"^\s*[\[(]?\s*\d{1,2}:\d{1,2}(?::\d{1,2})?(?:[.,]\d{1,3})?\s*[\])]?\s*[-:]?\s*",
        "", text, flags=re.MULTILINE,
    )
    # Collapse 3+ newlines to 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ============================================================================
# Text extraction — dispatches on file extension
# ============================================================================

class UnsupportedFormatError(ValueError):
    """Raised when extract_text is called on an unsupported file type."""


class MissingDependencyError(ImportError):
    """Raised when an optional extractor library isn't installed."""


def extract_text(path: Path) -> str:
    """Return the plain-text contents of a file in any supported format.
    Raises UnsupportedFormatError or MissingDependencyError on failure."""
    ext = path.suffix.lower()
    if ext in PLAIN_EXTS:
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return path.read_text(encoding="utf-8", errors="replace")
    if ext in DOCX_EXTS:
        return _extract_docx(path)
    if ext in PDF_EXTS:
        return _extract_pdf(path)
    if ext in EPUB_EXTS:
        return _extract_epub(path)
    raise UnsupportedFormatError(f"Unsupported format: {ext} ({path.name})")


def _extract_docx(path: Path) -> str:
    try:
        from docx import Document
    except ImportError as e:
        raise MissingDependencyError(
            "python-docx not installed. Run: pip install python-docx"
        ) from e
    doc = Document(str(path))
    return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())


def _extract_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise MissingDependencyError(
            "pypdf not installed. Run: pip install pypdf"
        ) from e
    reader = PdfReader(str(path))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(p.strip() for p in pages if p.strip())


def _extract_epub(path: Path) -> str:
    try:
        from ebooklib import epub, ITEM_DOCUMENT
        from bs4 import BeautifulSoup
    except ImportError as e:
        raise MissingDependencyError(
            "ebooklib + beautifulsoup4 not installed. "
            "Run: pip install ebooklib beautifulsoup4"
        ) from e
    book = epub.read_epub(str(path))
    chapters = []
    for item in book.get_items_of_type(ITEM_DOCUMENT):
        soup = BeautifulSoup(item.get_content(), "html.parser")
        # Drop scripts / styles
        for tag in soup(["script", "style"]):
            tag.decompose()
        chapters.append(soup.get_text(separator="\n"))
    return "\n\n".join(c.strip() for c in chapters if c.strip())


# ============================================================================
# TTS rendering
# ============================================================================

async def render_text_to_file(
    text: str,
    output_path: Path,
    voice: str = DEFAULT_VOICE,
    rate: str = DEFAULT_RATE,
    pitch: str = DEFAULT_PITCH,
) -> None:
    """Synthesize `text` to an MP3 at `output_path`. Writes atomically: a
    `.part` file is produced first then renamed on completion, so a partial
    `.mp3` can never be left next to the source if the user kills the run."""
    cleaned = strip_markdown(text).strip()
    if not cleaned:
        raise ValueError("Text is empty after cleanup; nothing to synthesize.")
    communicate = edge_tts.Communicate(
        cleaned, voice=voice, rate=rate, pitch=pitch,
    )
    tmp = output_path.with_suffix(output_path.suffix + ".part")
    try:
        await communicate.save(str(tmp))
        tmp.replace(output_path)
    except Exception:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise


async def render_text_to_bytes(
    text: str,
    voice: str = DEFAULT_VOICE,
    rate: str = DEFAULT_RATE,
    pitch: str = DEFAULT_PITCH,
) -> bytes:
    """Synthesize `text` to MP3 bytes (no disk write). Used by the local
    web app to stream the audio back to the browser."""
    cleaned = strip_markdown(text).strip()
    if not cleaned:
        raise ValueError("Text is empty after cleanup; nothing to synthesize.")
    communicate = edge_tts.Communicate(
        cleaned, voice=voice, rate=rate, pitch=pitch,
    )
    chunks: list[bytes] = []
    async for chunk in communicate.stream():
        if chunk.get("type") == "audio":
            chunks.append(chunk["data"])
    return b"".join(chunks)


# ============================================================================
# Folder scanning — picks files that need rendering
# ============================================================================

def discover_unrendered(folder: Path, force: bool = False) -> list[Path]:
    """Walk `folder` (non-recursive) and return text/doc/pdf/epub files that
    don't yet have a sibling audio file with the same stem. With `force=True`,
    return every supported text-bearing file regardless."""
    if not folder.is_dir():
        return []
    by_stem: dict[str, list[Path]] = {}
    for entry in folder.iterdir():
        if entry.is_file():
            by_stem.setdefault(entry.stem, []).append(entry)

    targets: list[Path] = []
    for stem, group in by_stem.items():
        text_files = [f for f in group if f.suffix.lower() in SUPPORTED_TEXT_EXTS]
        audio_files = [f for f in group if f.suffix.lower() in AUDIO_EXTS]
        if not text_files:
            continue
        if audio_files and not force:
            continue
        # Prefer richer formats first when a stem has multiple
        order = {".md": 0, ".markdown": 1, ".txt": 2,
                 ".docx": 3, ".pdf": 4, ".epub": 5}
        text_files.sort(key=lambda f: order.get(f.suffix.lower(), 99))
        targets.append(text_files[0])
    return targets


# ============================================================================
# Convenience: list all available voices (delegates to edge-tts)
# ============================================================================

async def list_all_voices() -> list[dict]:
    """Return the full Edge TTS voice catalog as a list of dicts."""
    return await edge_tts.list_voices()


# ============================================================================
# Translation — English → Latin American Spanish (or any pair)
# ============================================================================
# Uses deep-translator's GoogleTranslator backend, which hits Google's free
# unofficial web endpoint. No API key, but rate-limited and brittle in the
# same way edge-tts is brittle (Google can change the protocol). For the
# typical use case — convert a chapter / article / .txt for personal study —
# this is fine. Long inputs are chunked at paragraph boundaries to stay
# under Google's per-request character limit.

# Google's per-request limit is ~5000 chars. We aim for under 4500 to leave
# room for the URL-encoded form, headers, etc.
_TRANSLATE_CHUNK_LIMIT = 4500


def translate_text(
    text: str,
    target_lang: str = "es",
    source_lang: str = "auto",
    progress: Optional[callable] = None,
) -> str:
    """Translate `text` to `target_lang` (ISO 639-1, e.g. 'es' for Spanish).
    Chunks long inputs on paragraph boundaries; falls back to sentence
    splitting for very long single paragraphs.

    `progress`, if given, is called as `progress(done_chunks, total_chunks)`
    after each chunk completes — lets the GUI show a per-chunk indicator
    while a long file is translating.
    """
    try:
        from deep_translator import GoogleTranslator
    except ImportError as e:
        raise MissingDependencyError(
            "deep-translator not installed. Run: pip install deep-translator"
        ) from e

    text = text.strip()
    if not text:
        return ""

    translator = GoogleTranslator(source=source_lang, target=target_lang)

    # Fast path: short enough to send in one call.
    if len(text) <= _TRANSLATE_CHUNK_LIMIT:
        if progress:
            progress(0, 1)
        out = translator.translate(text) or ""
        if progress:
            progress(1, 1)
        return out

    # Slow path: split on double newlines, then on sentences for any
    # paragraph that itself exceeds the limit.
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    def _flush():
        nonlocal current, current_len
        if current:
            chunks.append("\n\n".join(current))
            current = []
            current_len = 0

    for paragraph in text.split("\n\n"):
        plen = len(paragraph)
        if plen > _TRANSLATE_CHUNK_LIMIT:
            _flush()
            # Split this paragraph into sentence-sized pieces
            sentences = re.split(r"(?<=[.!?…])\s+", paragraph)
            sub: list[str] = []
            sub_len = 0
            for sentence in sentences:
                slen = len(sentence)
                if sub_len + slen > _TRANSLATE_CHUNK_LIMIT and sub:
                    chunks.append(" ".join(sub))
                    sub = []
                    sub_len = 0
                sub.append(sentence)
                sub_len += slen + 1
            if sub:
                chunks.append(" ".join(sub))
        else:
            if current_len + plen > _TRANSLATE_CHUNK_LIMIT and current:
                _flush()
            current.append(paragraph)
            current_len += plen + 2
    _flush()

    total = len(chunks)
    out_parts: list[str] = []
    for i, c in enumerate(chunks):
        if progress:
            progress(i, total)
        out_parts.append(translator.translate(c) or "")
    if progress:
        progress(total, total)
    return "\n\n".join(out_parts)
