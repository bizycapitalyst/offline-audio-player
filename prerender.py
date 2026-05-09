#!/usr/bin/env python3
"""
prerender.py — Pre-render Markdown / text transcripts to MP3 using
Microsoft Edge's neural TTS (free, no API key) so they play in the
Offline Audio Player with TRUE background support (screen off, lockscreen
controls). Browser TTS gets paused when the tab is backgrounded; once a
transcript is rendered to MP3, it's a regular audio file and plays
uninterrupted.

Usage:
    python prerender.py [folder]                    # render any unmatched .md/.txt
    python prerender.py --voice jenny               # pick a different US voice
    python prerender.py --rate -10%%                 # slower; +5%% for faster
    python prerender.py --force                     # re-render even if MP3 exists
    python prerender.py --list-voices               # see available voices

Voice presets (all en-US neural):
    aria, jenny, guy, ana, christopher, eric, michelle, roger, steffan
You can also pass any full Edge voice name like "en-GB-RyanNeural".

Network is required at generation time. The resulting MP3s play offline.

Install:  pip install -r requirements.txt
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

try:
    import edge_tts
except ImportError:
    print(
        "Missing dependency. Install with:\n    pip install -r requirements.txt",
        file=sys.stderr,
    )
    sys.exit(1)

AUDIO_EXTS = {".mp3", ".m4a", ".wav", ".ogg", ".oga", ".opus", ".flac", ".aac", ".webm", ".mp4"}
TEXT_EXTS = {".txt", ".md", ".markdown"}

DEFAULT_VOICE = "en-US-AriaNeural"
DEFAULT_RATE = "-5%"   # Slightly slower for natural pacing
DEFAULT_PITCH = "+0Hz"

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


def strip_markdown(text: str) -> str:
    """Light cleanup so the TTS engine reads prose, not markdown syntax."""
    # Code fences: keep inner text, drop the fences
    text = re.sub(r"```[a-zA-Z0-9_+-]*\n([\s\S]*?)```", r"\1", text)
    # Inline code: drop backticks
    text = re.sub(r"`([^`]+)`", r"\1", text)
    # Images: keep alt text only
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    # Links: keep visible text only
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # Headings: drop leading #s
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
    # Leading timestamps like [00:01:23] - drop, the audio will have its own clock
    text = re.sub(
        r"^\s*[\[(]?\s*\d{1,2}:\d{1,2}(?::\d{1,2})?(?:[.,]\d{1,3})?\s*[\])]?\s*[-:]?\s*",
        "",
        text,
        flags=re.MULTILINE,
    )
    # Collapse 3+ newlines to 2 (preserves paragraph breaks for natural pauses)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


async def render_one(
    src: Path,
    dst: Path,
    voice: str,
    rate: str,
    pitch: str,
) -> bool:
    try:
        raw = src.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raw = src.read_text(encoding="utf-8", errors="replace")

    cleaned = strip_markdown(raw)
    if not cleaned:
        print(f"  skip (empty after cleanup): {src.name}")
        return False

    communicate = edge_tts.Communicate(
        cleaned,
        voice=voice,
        rate=rate,
        pitch=pitch,
    )
    # Stream to a temp file then atomically rename, so a Ctrl-C mid-render
    # doesn't leave a half-written MP3 next to the transcript.
    tmp = dst.with_suffix(dst.suffix + ".part")
    try:
        await communicate.save(str(tmp))
        tmp.replace(dst)
    except Exception:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise
    return True


async def main_async(
    folder: Path, voice: str, rate: str, pitch: str, force: bool,
    lang_mode: str = "english",
    es_voice: str = "es-MX-DaliaNeural",
    save_translated_text: bool = True,
) -> int:
    files = [f for f in folder.iterdir() if f.is_file()]
    by_base: dict[str, list[Path]] = {}
    for f in files:
        by_base.setdefault(f.stem, []).append(f)

    do_en = lang_mode in ("english", "both")
    do_es = lang_mode in ("spanish", "both")

    targets: list[Path] = []
    for base, group in by_base.items():
        text_files = [f for f in group if f.suffix.lower() in TEXT_EXTS]
        audio_files = [f for f in group if f.suffix.lower() in AUDIO_EXTS]
        if not text_files:
            continue
        if audio_files and not force:
            continue
        # Preference order: .md > .markdown > .txt
        text_files.sort(
            key=lambda f: 0 if f.suffix.lower() == ".md"
            else (1 if f.suffix.lower() == ".markdown" else 2)
        )
        targets.append(text_files[0])

    if not targets:
        print("Nothing to render.")
        print("(No transcripts found without a matching audio file. Use --force to re-render.)")
        return 0

    print(f"Output: {lang_mode}")
    print(f"En voice: {voice}    Es voice: {es_voice if do_es else '-'}")
    print(f"Rate:   {rate}    Pitch: {pitch}")
    print(f"Folder: {folder}")
    print(f"Targets ({len(targets)}):")
    for src in targets:
        print(f"  {src.name}")
    print()

    # Lazy-import the translation helper only when Spanish output is requested.
    # Keeps the CLI usable without deep-translator installed for English-only use.
    translate = None
    if do_es:
        try:
            from tts_lib import translate_text as _translate
            translate = _translate
        except ImportError:
            print("ERROR: deep-translator (or tts_lib) not available — Spanish output requires it.",
                  file=sys.stderr)
            print("       pip install deep-translator", file=sys.stderr)
            return 1

    rendered = 0
    failed = 0
    total_outputs = len(targets) * (int(do_en) + int(do_es))
    for src in targets:
        # ---- English ---------------------------------------------------
        if do_en:
            en_dst = folder / (src.stem + ".mp3")
            print(f"-> [en] {src.name}  =>  {en_dst.name}")
            try:
                ok = await render_one(src, en_dst, voice, rate, pitch)
                if ok:
                    rendered += 1
                else:
                    failed += 1
            except Exception as e:
                print(f"   FAILED: {e}", file=sys.stderr)
                failed += 1

        # ---- Spanish ---------------------------------------------------
        if do_es:
            es_audio_dst = folder / (src.stem + ".es.mp3")
            es_text_dst = folder / (src.stem + ".es.txt")
            print(f"-> [es] {src.name}  =>  {es_audio_dst.name}")
            try:
                # extract text (re-using strip_markdown via render_one isn't
                # possible since translate needs the cleaned source first)
                try:
                    raw = src.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    raw = src.read_text(encoding="utf-8", errors="replace")
                cleaned = strip_markdown(raw).strip()
                if not cleaned:
                    print("   skipped (empty after cleanup)")
                    continue
                print("   translating...")
                translated = translate(cleaned, target_lang="es")
                if save_translated_text:
                    es_text_dst.write_text(translated, encoding="utf-8")
                    print(f"   wrote {es_text_dst.name}")
                # render translated text
                import edge_tts as _edge
                tmp = es_audio_dst.with_suffix(es_audio_dst.suffix + ".part")
                try:
                    await _edge.Communicate(
                        translated, voice=es_voice, rate=rate, pitch=pitch,
                    ).save(str(tmp))
                    tmp.replace(es_audio_dst)
                    rendered += 1
                except Exception:
                    if tmp.exists():
                        try: tmp.unlink()
                        except OSError: pass
                    raise
            except Exception as e:
                print(f"   FAILED: {e}", file=sys.stderr)
                failed += 1

    print()
    print(f"Done. {rendered}/{total_outputs} rendered.")
    return 0 if failed == 0 else 2


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Pre-render markdown/text transcripts to MP3 using Edge neural TTS.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("folder", nargs="?", default=".", help="Folder to scan (default: current).")
    p.add_argument(
        "--voice", "-v", default=DEFAULT_VOICE,
        help=f"Voice alias ({', '.join(US_VOICES)}) or full name. Default: {DEFAULT_VOICE}.",
    )
    p.add_argument(
        "--rate", "-r", default=DEFAULT_RATE,
        help=f"Speaking rate, e.g. -10%%, +5%%. Default: {DEFAULT_RATE}.",
    )
    p.add_argument(
        "--pitch", "-p", default=DEFAULT_PITCH,
        help=f"Pitch in Hz, e.g. -5Hz, +5Hz. Default: {DEFAULT_PITCH}.",
    )
    p.add_argument(
        "--force", "-f", action="store_true",
        help="Re-render even if a matching audio file already exists.",
    )
    p.add_argument(
        "--lang", "-l", default="english", choices=["english", "spanish", "both"],
        help="Output language: 'english' (default), 'spanish' (translated to "
             "Latin American Spanish), or 'both'. Spanish requires "
             "deep-translator (pip install deep-translator).",
    )
    p.add_argument(
        "--spanish-voice", default="es-MX-DaliaNeural",
        help="Spanish voice (full Edge name or short alias: dalia, jorge, "
             "paloma, alonso, salome, gonzalo, camila, alex, elena, tomas). "
             "Default: es-MX-DaliaNeural.",
    )
    p.add_argument(
        "--no-translated-text", action="store_true",
        help="Skip writing the translated text as <name>.es.txt alongside the "
             "Spanish .mp3. By default the .es.txt is saved so the audio "
             "player can pair it as a Spanish transcript.",
    )
    p.add_argument(
        "--list-voices", action="store_true",
        help="List recommended US English voices and exit.",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if args.list_voices:
        print("Recommended US English neural voices:")
        for alias, name in US_VOICES.items():
            print(f"  {alias:14s} -> {name}")
        print("\nFor the full catalog (other languages too), run:")
        print("  python -m edge_tts --list-voices")
        return 0

    voice = US_VOICES.get(args.voice.lower(), args.voice)

    # Resolve Spanish voice alias if the user passed a short name.
    SPANISH_ALIASES = {
        "dalia":   "es-MX-DaliaNeural", "jorge":   "es-MX-JorgeNeural",
        "paloma":  "es-US-PalomaNeural", "alonso":  "es-US-AlonsoNeural",
        "salome":  "es-CO-SalomeNeural", "gonzalo": "es-CO-GonzaloNeural",
        "camila":  "es-PE-CamilaNeural", "alex":    "es-PE-AlexNeural",
        "elena":   "es-AR-ElenaNeural",  "tomas":   "es-AR-TomasNeural",
    }
    es_voice = SPANISH_ALIASES.get(args.spanish_voice.lower(), args.spanish_voice)

    folder = Path(args.folder).expanduser().resolve()
    if not folder.is_dir():
        print(f"Not a directory: {folder}", file=sys.stderr)
        return 1
    try:
        return asyncio.run(main_async(
            folder, voice, args.rate, args.pitch, args.force,
            lang_mode=args.lang,
            es_voice=es_voice,
            save_translated_text=not args.no_translated_text,
        ))
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
