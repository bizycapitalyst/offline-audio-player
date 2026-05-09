#!/usr/bin/env python3
"""
prerender_web.py — Local browser-based UI for the TTS pre-renderer.

Run:
    python prerender_web.py [--port 8765] [--host 127.0.0.1]

Then open http://127.0.0.1:8765/ in any browser. Drag in or pick a file
(.txt / .md / .docx / .pdf / .epub), pick a voice, click Convert, and the
generated .mp3 downloads to your default Downloads folder.

Why this exists alongside the Tkinter GUI:
    - cross-platform identical UI (no Windows-only theming quirks)
    - usable from a different machine on the same LAN if you're at your
      desk and want to render text from your phone's browser
    - no Python GUI dependencies, only stdlib http.server

Implementation:
    - Single-process stdlib HTTP server.
    - The HTML / JS frontend is embedded as a string below.
    - POST /api/render returns the mp3 bytes; the browser saves it.
"""
from __future__ import annotations

import argparse
import asyncio
import io
import json
import sys
import threading
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import tts_lib

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


# ============================================================================
# HTML page (served at /). Self-contained — no external CSS/JS.
# Theming intentionally mirrors the audio_player PWA so the two feel related.
# ============================================================================

PAGE_HTML = r"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TTS Converter</title>
<style>
  :root {
    --bg:#0a0a0d; --bg-card:#16161d; --bg-tile:#1c1c25; --bg-input:#1f1f29;
    --bg-hover:#23232f; --border:#26262f; --border-soft:#1e1e26;
    --text:#ededf0; --text-mid:#a8a8b3; --text-dim:#6a6a76;
    --accent:#fbbf24; --accent-soft:rgba(251,191,36,0.13);
    --good:#34d399; --bad:#f87171;
  }
  * { box-sizing:border-box; }
  body {
    margin:0; padding:18px; max-width:560px; margin:0 auto;
    background:var(--bg); color:var(--text);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Inter",Roboto,sans-serif;
    font-size:15px; line-height:1.5;
  }
  h1 { font-size:18px; font-weight:600; margin:14px 0 18px; }
  h1 .sub { color:var(--text-dim); font-size:12px; font-weight:400; display:block; margin-top:2px; }
  .card { background:var(--bg-card); border:1px solid var(--border-soft); border-radius:14px; padding:16px; margin-bottom:14px; box-shadow:0 1px 0 rgba(255,255,255,0.04) inset, 0 8px 24px -12px rgba(0,0,0,0.5); }
  label.lbl { display:block; font-size:11px; font-weight:600; letter-spacing:0.08em; text-transform:uppercase; color:var(--text-dim); margin-bottom:8px; }
  .drop {
    border:2px dashed var(--border); border-radius:10px; padding:28px 16px;
    text-align:center; color:var(--text-dim); cursor:pointer; transition: all .15s;
  }
  .drop.over { border-color:var(--accent); background:var(--accent-soft); color:var(--accent); }
  .drop b { color:var(--text); }
  input[type=file] { display:none; }
  .file-info { margin-top:10px; font-size:12px; color:var(--text-mid); min-height:18px; }
  .row { display:grid; grid-template-columns: 90px 1fr 60px; gap:10px; align-items:center; margin-top:10px; }
  .row label { font-size:12px; color:var(--text-dim); }
  select, input[type=range], input[type=text], button {
    font-family:inherit; font-size:14px; color:var(--text);
    background:var(--bg-tile); border:1px solid var(--border);
    border-radius:8px; padding:8px 12px; width:100%;
  }
  input[type=range] { padding:0; height:6px; background:var(--border); accent-color:var(--accent); }
  .val { text-align:right; font-variant-numeric:tabular-nums; font-size:12px; color:var(--text-mid); }
  button.primary {
    background:var(--accent); border-color:var(--accent); color:#1a1004;
    font-weight:700; cursor:pointer;
    padding:12px 16px; font-size:14px;
    box-shadow:0 4px 14px -4px rgba(251,191,36,0.4);
  }
  button.primary:disabled { opacity:0.5; cursor:not-allowed; }
  .progress { width:100%; height:6px; background:var(--border); border-radius:3px; margin-top:10px; overflow:hidden; }
  .progress > div { height:100%; background:var(--accent); width:0%; transition: width .2s; }
  .status { font-size:12px; margin-top:8px; min-height:18px; color:var(--text-dim); }
  .status.warn { color:var(--bad); }
  .status.good { color:var(--good); }
  details { margin-top:10px; }
  details summary { cursor:pointer; color:var(--text-dim); font-size:11px; font-weight:600; letter-spacing:0.08em; text-transform:uppercase; }
  details .help { font-size:12.5px; color:var(--text-mid); margin-top:8px; line-height:1.6; }
  details code { background:var(--bg); padding:1px 5px; border-radius:4px; font-family:"SF Mono",Monaco,Consolas,monospace; font-size:0.9em; }
</style></head>
<body>
  <h1>TTS Converter
    <span class="sub">.txt / .md / .docx / .pdf / .epub  →  .mp3</span>
  </h1>

  <div class="card">
    <label class="lbl">Source</label>
    <div class="drop" id="drop">
      <div><b>Drop a file here</b> or click to pick</div>
      <div style="font-size:11px;margin-top:6px;">.txt · .md · .markdown · .docx · .pdf · .epub</div>
    </div>
    <input type="file" id="file" accept=".txt,.md,.markdown,.docx,.pdf,.epub">
    <div class="file-info" id="fileInfo"></div>
  </div>

  <div class="card">
    <label class="lbl">Voice & pacing</label>
    <div class="row">
      <label>Voice</label>
      <select id="voice"></select>
      <span></span>
    </div>
    <div class="row">
      <label>Rate</label>
      <input type="range" id="rate" min="-30" max="30" step="1" value="-5">
      <span class="val" id="rateVal">-5%</span>
    </div>
    <div class="row">
      <label>Pitch</label>
      <input type="range" id="pitch" min="-20" max="20" step="1" value="0">
      <span class="val" id="pitchVal">+0Hz</span>
    </div>
    <details>
      <summary>Custom voice (advanced)</summary>
      <div class="help">
        Pass any Edge voice name verbatim, e.g. <code>en-GB-RyanNeural</code>. Overrides the dropdown.
      </div>
      <input type="text" id="customVoice" placeholder="" style="margin-top:8px;">
    </details>
  </div>

  <div class="card">
    <button class="primary" id="go">Convert &rarr; download .mp3</button>
    <div class="progress" id="prog"><div></div></div>
    <div class="status" id="status"></div>
  </div>

<script>
const VOICES = __VOICES_JSON__;
const voiceSel = document.getElementById('voice');
for (const [alias, full] of Object.entries(VOICES)){
  const o = document.createElement('option');
  o.value = full;
  o.textContent = `${alias}  —  ${full}`;
  voiceSel.appendChild(o);
}
voiceSel.value = "en-US-AriaNeural";

const rate = document.getElementById('rate');
const rateVal = document.getElementById('rateVal');
const pitch = document.getElementById('pitch');
const pitchVal = document.getElementById('pitchVal');
const fmtRate = v => (v >= 0 ? '+' : '') + v + '%';
const fmtPitch = v => (v >= 0 ? '+' : '') + v + 'Hz';
rate.addEventListener('input', () => rateVal.textContent = fmtRate(+rate.value));
pitch.addEventListener('input', () => pitchVal.textContent = fmtPitch(+pitch.value));

const drop = document.getElementById('drop');
const fileInput = document.getElementById('file');
const fileInfo = document.getElementById('fileInfo');
let chosenFile = null;

drop.addEventListener('click', () => fileInput.click());
fileInput.addEventListener('change', () => setFile(fileInput.files[0]));
['dragenter','dragover'].forEach(ev => drop.addEventListener(ev, e => {
  e.preventDefault(); drop.classList.add('over');
}));
['dragleave','drop'].forEach(ev => drop.addEventListener(ev, e => {
  e.preventDefault(); drop.classList.remove('over');
}));
drop.addEventListener('drop', e => {
  if (e.dataTransfer.files && e.dataTransfer.files[0]) setFile(e.dataTransfer.files[0]);
});
function setFile(f){
  if (!f) return;
  chosenFile = f;
  fileInfo.textContent = `${f.name}  (${(f.size/1024).toFixed(1)} KB)`;
}

const goBtn = document.getElementById('go');
const prog = document.getElementById('prog').firstElementChild;
const status = document.getElementById('status');
const customVoice = document.getElementById('customVoice');

function setStatus(msg, cls){
  status.textContent = msg || '';
  status.className = 'status' + (cls ? ' ' + cls : '');
}

goBtn.addEventListener('click', async () => {
  if (!chosenFile){ setStatus('Pick a file first.', 'warn'); return; }
  const voice = customVoice.value.trim() || voiceSel.value;
  const r = +rate.value;
  const p = +pitch.value;
  const fd = new FormData();
  fd.append('file', chosenFile);
  fd.append('voice', voice);
  fd.append('rate', fmtRate(r));
  fd.append('pitch', fmtPitch(p));
  goBtn.disabled = true;
  prog.style.width = '20%';
  setStatus('extracting + rendering…');
  try {
    const resp = await fetch('/api/render', { method:'POST', body: fd });
    if (!resp.ok){
      const txt = await resp.text();
      throw new Error(txt || ('HTTP ' + resp.status));
    }
    prog.style.width = '90%';
    const blob = await resp.blob();
    const baseName = chosenFile.name.replace(/\.[^.]+$/, '') + '.mp3';
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = baseName;
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
    prog.style.width = '100%';
    setStatus(`done — ${baseName} downloaded.`, 'good');
  } catch(err){
    setStatus('failed: ' + err.message, 'warn');
    prog.style.width = '0%';
  } finally {
    goBtn.disabled = false;
    setTimeout(() => prog.style.width = '0%', 1500);
  }
});
</script>
</body></html>
"""


def _build_html() -> bytes:
    """Inject the voice list into the page template at startup so the JS
    dropdown matches the lib's known voices."""
    voices_json = json.dumps(tts_lib.US_VOICES)
    return PAGE_HTML.replace("__VOICES_JSON__", voices_json).encode("utf-8")


_HTML_CACHE: bytes | None = None


# ============================================================================
# Multipart parser — minimal, just enough for our single-file form. We don't
# pull in a parser library because we want to stay stdlib-only here.
# ============================================================================

def _parse_multipart(body: bytes, boundary: str) -> dict:
    """Parse a multipart/form-data body. Returns {field_name: value} where
    value is bytes for file fields and str for text fields."""
    sep = b"--" + boundary.encode("ascii")
    fields: dict = {}
    parts = body.split(sep)
    for part in parts:
        if not part or part in (b"--\r\n", b"--", b"\r\n"):
            continue
        # Strip leading CRLF and trailing CRLF
        part = part.strip(b"\r\n")
        if part == b"--":
            continue
        # Split headers from content
        try:
            head_blob, content = part.split(b"\r\n\r\n", 1)
        except ValueError:
            continue
        # Trim trailing CRLF off content
        if content.endswith(b"\r\n"):
            content = content[:-2]
        # Parse Content-Disposition for the field name (and optional filename)
        headers = head_blob.decode("utf-8", errors="replace").split("\r\n")
        name = None
        is_file = False
        for h in headers:
            if h.lower().startswith("content-disposition"):
                # naive parse
                for token in h.split(";"):
                    token = token.strip()
                    if token.startswith("name="):
                        name = token[5:].strip('"')
                    elif token.startswith("filename="):
                        is_file = True
        if not name:
            continue
        if is_file:
            fields[name] = content  # raw bytes
        else:
            fields[name] = content.decode("utf-8", errors="replace")
    return fields


# ============================================================================
# HTTP handler
# ============================================================================

class _Handler(BaseHTTPRequestHandler):
    server_version = "TTSConverter/1.0"

    def log_message(self, fmt, *args):
        # Quieter access log
        sys.stderr.write(f"[{self.log_date_time_string()}] {fmt % args}\n")

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/?"):
            global _HTML_CACHE
            if _HTML_CACHE is None:
                _HTML_CACHE = _build_html()
            self._send_bytes(HTTPStatus.OK, "text/html; charset=utf-8", _HTML_CACHE)
        else:
            self._send_text(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self):
        if self.path != "/api/render":
            self._send_text(HTTPStatus.NOT_FOUND, "Not found")
            return
        ctype = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in ctype:
            self._send_text(HTTPStatus.BAD_REQUEST, "expected multipart/form-data")
            return
        # Extract boundary
        boundary = None
        for part in ctype.split(";"):
            part = part.strip()
            if part.startswith("boundary="):
                boundary = part[len("boundary="):].strip('"')
        if not boundary:
            self._send_text(HTTPStatus.BAD_REQUEST, "no multipart boundary")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        body = self.rfile.read(length) if length > 0 else b""
        fields = _parse_multipart(body, boundary)
        if "file" not in fields:
            self._send_text(HTTPStatus.BAD_REQUEST, "missing file field")
            return

        file_bytes: bytes = fields["file"]
        voice = (fields.get("voice") or tts_lib.DEFAULT_VOICE).strip() or tts_lib.DEFAULT_VOICE
        rate = (fields.get("rate") or tts_lib.DEFAULT_RATE).strip() or tts_lib.DEFAULT_RATE
        pitch = (fields.get("pitch") or tts_lib.DEFAULT_PITCH).strip() or tts_lib.DEFAULT_PITCH

        # Need to figure out the source ext to pick the right extractor.
        # Browsers don't tell us inline; but the form gave us a filename via
        # Content-Disposition. Re-parse just enough to get it.
        filename = self._extract_filename(body, boundary)
        suffix = Path(filename).suffix.lower() if filename else ".txt"
        if suffix not in tts_lib.SUPPORTED_TEXT_EXTS:
            self._send_text(HTTPStatus.BAD_REQUEST, f"unsupported format: {suffix}")
            return

        # Write to a temp file, extract, render to bytes, return.
        try:
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(file_bytes)
                tmp_path = Path(tmp.name)
            try:
                text = tts_lib.extract_text(tmp_path)
            finally:
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
        except tts_lib.MissingDependencyError as e:
            self._send_text(HTTPStatus.BAD_REQUEST, str(e))
            return
        except Exception as e:
            self._send_text(HTTPStatus.BAD_REQUEST, f"extract failed: {e}")
            return

        # Render synchronously on this request thread (a fresh asyncio loop).
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                mp3 = loop.run_until_complete(
                    tts_lib.render_text_to_bytes(
                        text, voice=voice, rate=rate, pitch=pitch,
                    )
                )
            finally:
                loop.close()
        except Exception as e:
            self._send_text(HTTPStatus.INTERNAL_SERVER_ERROR, f"render failed: {e}")
            return

        out_name = (Path(filename).stem if filename else "output") + ".mp3"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("Content-Length", str(len(mp3)))
        self.send_header("Content-Disposition", f'attachment; filename="{out_name}"')
        self.end_headers()
        self.wfile.write(mp3)

    # -- helpers --

    def _extract_filename(self, body: bytes, boundary: str) -> str:
        """Pull the original filename out of the multipart Content-Disposition
        for the 'file' field. Cheap re-parse rather than threading it through
        _parse_multipart to keep that function's return shape simple."""
        sep = b"--" + boundary.encode("ascii")
        for part in body.split(sep):
            if b"name=\"file\"" not in part:
                continue
            try:
                head_blob, _ = part.split(b"\r\n\r\n", 1)
            except ValueError:
                continue
            for line in head_blob.decode("utf-8", errors="replace").split("\r\n"):
                if "filename=" in line:
                    for token in line.split(";"):
                        token = token.strip()
                        if token.startswith("filename="):
                            return token[len("filename="):].strip('"')
        return ""

    def _send_bytes(self, status, ctype, payload: bytes):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _send_text(self, status, text: str):
        self._send_bytes(status, "text/plain; charset=utf-8", text.encode("utf-8"))


# ============================================================================
# Entry point
# ============================================================================

def main() -> int:
    p = argparse.ArgumentParser(description="Local web app for the TTS pre-renderer.")
    p.add_argument("--host", default=DEFAULT_HOST, help=f"bind host (default: {DEFAULT_HOST})")
    p.add_argument("--port", type=int, default=DEFAULT_PORT,
                   help=f"port (default: {DEFAULT_PORT})")
    p.add_argument("--no-open", action="store_true",
                   help="don't auto-open the browser")
    args = p.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), _Handler)
    url = f"http://{args.host}:{args.port}/"
    print(f"TTS Converter web app running at {url}")
    print("Press Ctrl-C to stop.")
    if not args.no_open:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
        print("shutting down...")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
