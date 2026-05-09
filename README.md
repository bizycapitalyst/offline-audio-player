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

Included is `prerender.py`, a small script that does this with Microsoft Edge's neural TTS (free, no API key, US English voices).

```bash
pip install -r requirements.txt
python prerender.py /path/to/your/audio/folder
```

For each `.md` / `.txt` file in that folder that doesn't already have a matching audio file, it produces a same-base-name `.mp3` using a US voice with natural pacing. Sync that folder to your phone and the player picks them up automatically.

Common options:

```bash
python prerender.py --voice jenny             # different US voice
python prerender.py --rate -10%               # slower
python prerender.py --rate +5%                # faster
python prerender.py --force                   # re-render even if mp3 exists
python prerender.py --list-voices             # see available voices
```

US voice presets: `aria` (default), `jenny`, `guy`, `ana`, `christopher`, `eric`, `michelle`, `roger`, `steffan`.

The script needs network only at generation time. The resulting MP3s play offline.

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
| `prerender.py` | TTS pre-renderer for background-capable transcript playback. |
| `requirements.txt` | Python deps for `prerender.py`. |

## License

MIT
