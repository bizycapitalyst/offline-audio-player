# Offline Audio Player

A single-file HTML audio player for Android (and desktop) that:

- Auto-discovers audio files in a folder you pick
- Auto-pairs each audio with a same-named `.txt` / `.md` transcript
- Scrolls the transcript in sync with playback (timestamp-based or proportional)
- Maximizes the transcript to a full-screen reader view
- Reads transcripts aloud with a US English voice (in-browser TTS)
- Plays audio in the background with the screen off (Media Session / lockscreen controls)
- Works fully offline once loaded
- Auto-updates from GitHub when online

## Use it on your phone

The hosted version: **https://BizyCapitalyst.github.io/offline-audio-player/**

1. Open that URL in **Chrome on Android**.
2. Menu → **Add to Home Screen**.
3. Launch from the home screen, tap **Pick folder**, choose the folder with your audio files.
4. After first launch, it works in airplane mode.

When the device is online, the app silently checks for updates on launch. A green **update vX.Y.Z** badge appears in the header if a new version is available — tap it to reload.

## Use it offline-only (no GitHub Pages)

Download `index.html` (and optionally `sw.js` + `manifest.webmanifest`) and place it in any folder on your phone. Open it in a file-system-aware browser (Chrome on Android works).

Note: with `file://` URLs, service workers don't run — that's fine, the page is already local. The folder picker still works.

## Audio in the background / screen off

For any **regular audio file** (mp3, m4a, wav, ogg, opus, flac, aac, webm), background and lockscreen playback work via the standard Web Media Session API — start playback from the foreground, then lock the screen or switch apps; audio keeps going, with prev / pause / next on the lockscreen.

## True background **TTS** (transcripts spoken aloud, screen off)

The browser's built-in Read-Aloud uses the Web Speech API, which **most mobile browsers pause when backgrounded.** The fix is to render the transcript to an MP3 once on your PC, then play that MP3 — which gets full background treatment.

Included are **four entry points** that all use the same engine (Microsoft Edge's neural TTS, free, no API key, US English voices). Pick whichever fits how you work.

### 1. CLI — `prerender.py`

Fastest if you live in a terminal. Walks a folder, generates one MP3 per text file.

```bash
pip install -r requirements.txt
python prerender.py /path/to/your/audio/folder
```

Common options:

```bash
python prerender.py --voice jenny       # different US voice
python prerender.py --rate -10%         # slower
python prerender.py --force             # re-render even if mp3 exists
python prerender.py --list-voices       # see available voices
```

### 2. Desktop GUI — `prerender_gui.py`

Tkinter app: drag-and-drop files (or pick via dialog), choose voice / rate / pitch with sliders, watch a progress bar, see a per-file log.

```bash
python prerender_gui.py
```

### 3. Local web app — `prerender_web.py`

Same engine, browser UI. Useful cross-platform or if you want to render from another device on the same Wi-Fi.

```bash
python prerender_web.py            # opens http://127.0.0.1:8765/
python prerender_web.py --port 9000 --host 0.0.0.0   # LAN-accessible
```

### 4. Standalone Windows `.exe` — `build_exe.bat`

Bundles the GUI into a single double-clickable executable. No Python needed on the target machine.

```bat
pip install pyinstaller
build_exe.bat
```

Produces `dist\TTS_Converter.exe` (~30–50 MB). Copy it anywhere; it runs standalone.

### Audio → Text (Speech-to-Text)

The TTS Converter GUI / `.exe` has a second tab — **Audio → Text** — that runs the reverse direction: transcribe `.mp3` / `.wav` / `.m4a` / etc. into a `.txt` file. Powered by **faster-whisper** (open-source OpenAI Whisper on CTranslate2 — free, no API key, runs locally on CPU).

| Setting | Options | Notes |
|---|---|---|
| Model | `tiny-en` (39 MB) / `base-en` (74 MB, default) / `small-en` (244 MB) / `medium-en` (769 MB) / multilingual variants | First use of each model downloads to `~/.cache/huggingface/hub/`; cached after that. English-only (`-en`) models are slightly better + faster on English audio. |
| Language | English / Spanish / Auto-detect | Auto-detect requires a multilingual model (the non-`-en` variants). |
| Translate to English | checkbox | Only meaningful when the source language is non-English. Uses Whisper's built-in translate task. Auto-selects a multilingual model. |
| Output | `.txt` next to the audio file (default), or pick a folder | `name.txt` for plain transcribe; `name.en.txt` for translated-to-English; `name.es.txt` for Spanish source. |
| Re-transcribe even if .txt exists | checkbox (on by default) | |

Performance: `base-en` on CPU runs roughly 5–10× realtime, so a 10-minute audio takes ~1–2 minutes. The first run also includes a one-time model download (74 MB for `base-en`).

### English → Latin American Spanish translation

Each entry point can output **English only** (default), **Spanish only** (translated), or **Both**. Spanish output uses Microsoft Edge's Latin American neural voices (Mexican by default — the most "neutral" LatAm dialect). Translation runs through `deep-translator`'s Google backend (free, no API key, needs internet at convert time only).

| Output mode | Files produced (per source `chapter1.md`) |
|---|---|
| English only | `chapter1.mp3` |
| Spanish only | `chapter1.es.mp3` + `chapter1.es.txt` (the translated text, optional) |
| Both | `chapter1.mp3` + `chapter1.es.mp3` + `chapter1.es.txt` |

The `.es.txt` is saved by default so the audio player can pair the Spanish MP3 with a Spanish transcript (matching the same `name + .es` pattern). Skip it with the GUI's checkbox or the CLI's `--no-translated-text`.

CLI usage:

```bash
python prerender.py "..." --lang both                          # English + Spanish
python prerender.py "..." --lang spanish                       # Spanish only
python prerender.py "..." --lang spanish --spanish-voice jorge # different LatAm voice
```

LatAm Spanish voice presets: `dalia` (default, Mexico female), `jorge` (Mexico male), `paloma` / `alonso` (US Spanish), `salome` / `gonzalo` (Colombia), `camila` / `alex` (Peru), `elena` / `tomas` (Argentina). Or supply any full Edge voice name like `es-MX-DaliaNeural` directly.

### Supported input formats

All four entry points accept:

| Extension | Source | Library |
|---|---|---|
| `.txt`, `.md`, `.markdown` | plain / markdown text | stdlib |
| `.docx` | Microsoft Word documents | `python-docx` |
| `.pdf` | PDFs (text extracted via PyPDF) | `pypdf` |
| `.epub` | EPUB ebooks (chapter HTML stripped to plain text) | `ebooklib` + `beautifulsoup4` |

Each MP3 is written next to the source file by default. The GUI lets you pick a different output folder.

US voice presets: `aria` (default), `jenny`, `guy`, `ana`, `christopher`, `eric`, `michelle`, `roger`, `steffan`. Or supply any full Edge voice name (e.g. `en-GB-RyanNeural`) directly.

Network is needed only at generation time. The resulting MP3s play offline.

## Transcript timestamps

If your transcript lines start with timestamps, the player highlights the active line and tap-to-jump works:

```
[00:00:05] Welcome back.
[00:00:12] Today we're talking about...
1:23 - some other format also recognized
```

Recognized formats: `[h:mm:ss]`, `[mm:ss]`, `(mm:ss)`, `01:02:03`, with optional `-`, `–`, or `:` after the timestamp. Without timestamps, the transcript scrolls proportionally to the playback position.

## Releasing a new version

1. Edit `index.html` — bump the `APP_VERSION` constant near the top of the script block.
2. Edit `version.json` — same version, plus release notes.
3. Commit and push to `main`. GitHub Pages serves the new files within ~1 minute.
4. Existing users get a notification on next launch (when online) and can tap to update.

## Files

| File | Purpose |
|------|---------|
| `index.html` | The player. Single file, vanilla JS, no build step. |
| `sw.js` | Service worker — caches the shell, network-first for updates. |
| `manifest.webmanifest` | PWA metadata, icon, theme. |
| `version.json` | Version polled by the in-app update check. |
| `tts_lib.py` | Shared library — TTS rendering + multi-format text extraction (`.txt` / `.md` / `.docx` / `.pdf` / `.epub`). |
| `prerender.py` | CLI entry point — walks a folder, renders unrendered text files. |
| `prerender_gui.py` | Tkinter desktop GUI — drag-drop, voice picker, progress bar. |
| `prerender_web.py` | Local web app — same engine in a browser UI at `http://127.0.0.1:8765/`. |
| `build_exe.bat` | PyInstaller bundler — produces a single-file `TTS_Converter.exe`. |
| `requirements.txt` | Python deps for all four converter entry points. |

## License

MIT
