#!/usr/bin/env python3
"""
prerender_gui.py — Tkinter desktop GUI for the TTS pre-renderer.

What it does:
    Drag in (or pick) one or more text files (.txt, .md, .docx, .pdf, .epub)
    or a folder. Choose a US English voice + rate. Hit Convert. An .mp3
    file is written next to each input (or to a chosen output folder).

Why:
    Friendlier than `python prerender.py ...` from a terminal, and the
    multi-format support means you can drop a Word doc / PDF / EPUB and
    get an MP3 without any pre-extraction step.

Run:
    python prerender_gui.py

Optional drag-and-drop support: `pip install tkinterdnd2` (Windows/Mac/Linux).
Falls back to file/folder pickers if it's not installed.
"""
from __future__ import annotations

import asyncio
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import tts_lib

# Optional drag-and-drop. If this isn't installed the picker buttons still
# work — drag-drop is a nice-to-have, not the primary entry path.
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _HAS_DND = True
except ImportError:
    _HAS_DND = False

APP_TITLE = "TTS Converter"


# ============================================================================
# Async glue — runs the edge-tts coroutines on a background thread and
# posts progress updates back to the Tk main thread via a Queue.
# ============================================================================

class _Worker:
    """Drives the conversion in a background thread, posting progress
    messages to a thread-safe queue. The Tk main loop polls the queue and
    updates UI accordingly."""

    def __init__(self, on_message):
        self.q: queue.Queue = queue.Queue()
        self.on_message = on_message
        self.thread: threading.Thread | None = None
        self.cancel_flag = threading.Event()

    def start(self, files, voice, rate, pitch, output_dir, force,
              lang_mode="english", es_voice=tts_lib.DEFAULT_SPANISH_VOICE,
              save_translated_text=True):
        if self.thread and self.thread.is_alive():
            return False
        self.cancel_flag.clear()
        self.thread = threading.Thread(
            target=self._run,
            args=(files, voice, rate, pitch, output_dir, force,
                  lang_mode, es_voice, save_translated_text),
            daemon=True,
        )
        self.thread.start()
        return True

    def cancel(self):
        self.cancel_flag.set()

    def is_running(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    # -- internal --

    def _run(self, files, voice, rate, pitch, output_dir, force,
             lang_mode, es_voice, save_translated_text):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(
                self._convert_all(
                    files, voice, rate, pitch, output_dir, force,
                    lang_mode, es_voice, save_translated_text,
                )
            )
        except Exception as e:
            self.q.put(("error", f"unexpected: {e}"))
        finally:
            loop.close()
            self.q.put(("done", None))

    async def _convert_all(self, files, voice, rate, pitch, output_dir, force,
                            lang_mode, es_voice, save_translated_text):
        total = len(files)
        do_en = lang_mode in ("english", "both")
        do_es = lang_mode in ("spanish", "both")
        for idx, src_path in enumerate(files, start=1):
            if self.cancel_flag.is_set():
                self.q.put(("cancelled", None))
                return
            src = Path(src_path)
            self.q.put(("progress", {
                "i": idx, "total": total, "src": src.name, "phase": "extract",
            }))
            try:
                text = tts_lib.extract_text(src)
            except tts_lib.MissingDependencyError as e:
                self.q.put(("error", f"{src.name}: {e}"))
                continue
            except Exception as e:
                self.q.put(("error", f"{src.name}: extract failed — {e}"))
                continue

            dst_dir = output_dir if output_dir else src.parent

            # ---- English render --------------------------------------
            if do_en:
                en_dst = dst_dir / (src.stem + ".mp3")
                if en_dst.exists() and not force:
                    self.q.put(("skip", f"{src.name} → {en_dst.name} already exists"))
                else:
                    self.q.put(("progress", {
                        "i": idx, "total": total, "src": src.name, "phase": "render (en)",
                    }))
                    try:
                        await tts_lib.render_text_to_file(
                            text, en_dst, voice=voice, rate=rate, pitch=pitch,
                        )
                        self.q.put(("ok", f"{src.name} → {en_dst.name}"))
                    except Exception as e:
                        self.q.put(("error", f"{src.name}: render (en) failed — {e}"))

            if self.cancel_flag.is_set():
                self.q.put(("cancelled", None))
                return

            # ---- Spanish render --------------------------------------
            if do_es:
                es_audio_dst = dst_dir / (src.stem + ".es.mp3")
                es_text_dst = dst_dir / (src.stem + ".es.txt")
                already_have_audio = es_audio_dst.exists() and not force
                if already_have_audio:
                    self.q.put(("skip", f"{src.name} → {es_audio_dst.name} already exists"))
                else:
                    self.q.put(("progress", {
                        "i": idx, "total": total, "src": src.name, "phase": "translate",
                    }))
                    try:
                        translated = tts_lib.translate_text(text, target_lang="es")
                    except tts_lib.MissingDependencyError as e:
                        self.q.put(("error", f"{src.name}: {e}"))
                        continue
                    except Exception as e:
                        self.q.put(("error", f"{src.name}: translation failed — {e}"))
                        continue

                    # Optionally write the translated text alongside the MP3
                    # so the audio_player can pair them as a Spanish transcript.
                    if save_translated_text:
                        try:
                            es_text_dst.write_text(translated, encoding="utf-8")
                            self.q.put(("ok", f"{src.name} → {es_text_dst.name}"))
                        except Exception as e:
                            self.q.put(("error", f"{src.name}: write {es_text_dst.name} failed — {e}"))

                    self.q.put(("progress", {
                        "i": idx, "total": total, "src": src.name, "phase": "render (es)",
                    }))
                    try:
                        await tts_lib.render_text_to_file(
                            translated, es_audio_dst,
                            voice=es_voice, rate=rate, pitch=pitch,
                        )
                        self.q.put(("ok", f"{src.name} → {es_audio_dst.name}"))
                    except Exception as e:
                        self.q.put(("error", f"{src.name}: render (es) failed — {e}"))


# ============================================================================
# Tk app
# ============================================================================

class App:
    def __init__(self):
        self.root = TkinterDnD.Tk() if _HAS_DND else tk.Tk()
        self.root.title(APP_TITLE)
        self.root.geometry("680x560")
        self.root.minsize(560, 480)

        # Try a dark-ish theme; falls back to default on platforms without it
        try:
            style = ttk.Style()
            for theme in ("vista", "clam", "default"):
                if theme in style.theme_names():
                    style.theme_use(theme)
                    break
        except Exception:
            pass

        self.files: list[str] = []
        self.output_dir: Path | None = None
        self.worker = _Worker(on_message=self._on_worker_message)

        self._build_ui()
        self._poll_queue()

    # -- UI construction --

    def _build_ui(self):
        pad = {"padx": 10, "pady": 6}

        # Header
        header = ttk.Frame(self.root)
        header.pack(fill="x", **pad)
        ttk.Label(
            header, text=APP_TITLE,
            font=("Segoe UI", 14, "bold"),
        ).pack(side="left")
        ttk.Label(
            header,
            text="Convert .txt / .md / .docx / .pdf / .epub  →  .mp3",
            foreground="#666",
        ).pack(side="left", padx=(10, 0))

        # Files list with drop target
        files_frame = ttk.LabelFrame(self.root, text="Files to convert")
        files_frame.pack(fill="both", expand=True, **pad)

        list_wrap = ttk.Frame(files_frame)
        list_wrap.pack(fill="both", expand=True, padx=8, pady=(8, 0))
        scroll = ttk.Scrollbar(list_wrap, orient="vertical")
        scroll.pack(side="right", fill="y")
        self.file_list = tk.Listbox(
            list_wrap, yscrollcommand=scroll.set,
            selectmode="extended", activestyle="dotbox",
        )
        self.file_list.pack(side="left", fill="both", expand=True)
        scroll.config(command=self.file_list.yview)

        if _HAS_DND:
            self.file_list.drop_target_register(DND_FILES)
            self.file_list.dnd_bind("<<Drop>>", self._on_drop)

        btns = ttk.Frame(files_frame)
        btns.pack(fill="x", padx=8, pady=8)
        ttk.Button(btns, text="Add files…", command=self._pick_files).pack(side="left")
        ttk.Button(btns, text="Add folder…", command=self._pick_folder).pack(side="left", padx=(6, 0))
        ttk.Button(btns, text="Remove selected", command=self._remove_selected).pack(side="left", padx=(6, 0))
        ttk.Button(btns, text="Clear", command=self._clear).pack(side="left", padx=(6, 0))
        if _HAS_DND:
            ttk.Label(
                btns,
                text=" tip: drag files / folders onto the list",
                foreground="#888",
            ).pack(side="right")

        # Settings
        settings = ttk.LabelFrame(self.root, text="Voice & pacing")
        settings.pack(fill="x", **pad)

        row1 = ttk.Frame(settings); row1.pack(fill="x", padx=8, pady=4)
        ttk.Label(row1, text="Voice:", width=10).pack(side="left")
        self.voice_var = tk.StringVar(value="aria")
        voice_choices = list(tts_lib.US_VOICES.keys()) + ["(custom)"]
        self.voice_combo = ttk.Combobox(
            row1, textvariable=self.voice_var,
            values=voice_choices, state="readonly", width=18,
        )
        self.voice_combo.pack(side="left")
        self.voice_combo.bind("<<ComboboxSelected>>", self._on_voice_changed)
        self.custom_voice_var = tk.StringVar()
        self.custom_voice_entry = ttk.Entry(
            row1, textvariable=self.custom_voice_var, width=24,
        )
        self.custom_voice_entry.pack(side="left", padx=(6, 0))
        self.custom_voice_entry.insert(0, "")
        self.custom_voice_entry.configure(state="disabled")

        row2 = ttk.Frame(settings); row2.pack(fill="x", padx=8, pady=4)
        ttk.Label(row2, text="Rate:", width=10).pack(side="left")
        self.rate_var = tk.IntVar(value=-5)
        self.rate_scale = ttk.Scale(
            row2, from_=-30, to=30, orient="horizontal",
            variable=self.rate_var, command=self._on_rate_changed,
        )
        self.rate_scale.pack(side="left", fill="x", expand=True)
        self.rate_label = ttk.Label(row2, text="-5%", width=6, anchor="e")
        self.rate_label.pack(side="left", padx=(6, 0))

        row3 = ttk.Frame(settings); row3.pack(fill="x", padx=8, pady=4)
        ttk.Label(row3, text="Pitch:", width=10).pack(side="left")
        self.pitch_var = tk.IntVar(value=0)
        self.pitch_scale = ttk.Scale(
            row3, from_=-20, to=20, orient="horizontal",
            variable=self.pitch_var, command=self._on_pitch_changed,
        )
        self.pitch_scale.pack(side="left", fill="x", expand=True)
        self.pitch_label = ttk.Label(row3, text="+0Hz", width=6, anchor="e")
        self.pitch_label.pack(side="left", padx=(6, 0))

        row4 = ttk.Frame(settings); row4.pack(fill="x", padx=8, pady=4)
        ttk.Label(row4, text="Output:", width=10).pack(side="left")
        self.output_var = tk.StringVar(value="(same folder as each source file)")
        ttk.Entry(row4, textvariable=self.output_var, state="readonly").pack(
            side="left", fill="x", expand=True,
        )
        ttk.Button(row4, text="Pick…", command=self._pick_output).pack(side="left", padx=(6, 0))
        ttk.Button(row4, text="Reset", command=self._reset_output).pack(side="left", padx=(4, 0))

        row5 = ttk.Frame(settings); row5.pack(fill="x", padx=8, pady=4)
        self.force_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            row5, text="Re-render even if .mp3 already exists",
            variable=self.force_var,
        ).pack(side="left")

        # Output language (English / Spanish translation / Both)
        lang_frame = ttk.LabelFrame(self.root, text="Output language")
        lang_frame.pack(fill="x", **pad)

        rowL1 = ttk.Frame(lang_frame); rowL1.pack(fill="x", padx=8, pady=4)
        ttk.Label(rowL1, text="Output:", width=10).pack(side="left")
        self.lang_var = tk.StringVar(value="english")
        ttk.Radiobutton(
            rowL1, text="English only", variable=self.lang_var,
            value="english", command=self._on_lang_changed,
        ).pack(side="left", padx=(0, 12))
        ttk.Radiobutton(
            rowL1, text="Spanish only (translated)", variable=self.lang_var,
            value="spanish", command=self._on_lang_changed,
        ).pack(side="left", padx=(0, 12))
        ttk.Radiobutton(
            rowL1, text="Both", variable=self.lang_var,
            value="both", command=self._on_lang_changed,
        ).pack(side="left")

        rowL2 = ttk.Frame(lang_frame); rowL2.pack(fill="x", padx=8, pady=4)
        ttk.Label(rowL2, text="Spanish voice:", width=14).pack(side="left")
        self.es_voice_var = tk.StringVar(value="dalia")
        self.es_voice_combo = ttk.Combobox(
            rowL2, textvariable=self.es_voice_var,
            values=list(tts_lib.LATAM_SPANISH_VOICES.keys()),
            state="readonly", width=18,
        )
        self.es_voice_combo.pack(side="left")
        self.es_voice_hint = ttk.Label(
            rowL2,
            text="  Latin American Spanish (Mexican by default)",
            foreground="#888",
        )
        self.es_voice_hint.pack(side="left", padx=(8, 0))

        rowL3 = ttk.Frame(lang_frame); rowL3.pack(fill="x", padx=8, pady=4)
        self.save_translated_text_var = tk.BooleanVar(value=True)
        self.save_translated_text_chk = ttk.Checkbutton(
            rowL3,
            text="Also save the translated text as .es.txt  (pairs with the .es.mp3 in the audio player)",
            variable=self.save_translated_text_var,
        )
        self.save_translated_text_chk.pack(side="left")

        rowL4 = ttk.Frame(lang_frame); rowL4.pack(fill="x", padx=8, pady=(0, 4))
        self.lang_note = ttk.Label(
            rowL4,
            text="(Translation uses Google's free unofficial endpoint — needs internet at convert time.)",
            foreground="#888", font=("Segoe UI", 8),
        )
        self.lang_note.pack(side="left")

        # Sync the visibility of the Spanish-only controls
        self._on_lang_changed()

        # Action bar
        actions = ttk.Frame(self.root)
        actions.pack(fill="x", **pad)
        self.go_btn = ttk.Button(
            actions, text="Convert all", command=self._on_convert,
        )
        self.go_btn.pack(side="left")
        self.cancel_btn = ttk.Button(
            actions, text="Cancel", command=self._on_cancel, state="disabled",
        )
        self.cancel_btn.pack(side="left", padx=(6, 0))
        self.progress = ttk.Progressbar(actions, mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True, padx=(10, 0))

        # Log
        log_frame = ttk.LabelFrame(self.root, text="Log")
        log_frame.pack(fill="both", expand=True, **pad)
        self.log = tk.Text(log_frame, height=8, state="disabled", wrap="none")
        self.log.pack(fill="both", expand=True, padx=8, pady=8)

    # -- event handlers --

    def _on_voice_changed(self, _evt=None):
        if self.voice_var.get() == "(custom)":
            self.custom_voice_entry.configure(state="normal")
            self.custom_voice_entry.focus_set()
        else:
            self.custom_voice_entry.configure(state="disabled")

    def _on_lang_changed(self, _evt=None):
        """Show / hide the Spanish-specific controls based on the chosen
        output language. The widgets are kept in the layout regardless;
        we just toggle their enabled state so the layout doesn't reflow."""
        es_active = self.lang_var.get() in ("spanish", "both")
        state = "readonly" if es_active else "disabled"
        self.es_voice_combo.configure(state=state)
        self.es_voice_hint.configure(
            foreground=("#888" if es_active else "#444"),
        )
        chk_state = "normal" if es_active else "disabled"
        self.save_translated_text_chk.configure(state=chk_state)
        self.lang_note.configure(
            foreground=("#888" if es_active else "#444"),
        )

    def _on_rate_changed(self, _evt=None):
        v = int(round(float(self.rate_scale.get())))
        self.rate_var.set(v)
        sign = "+" if v >= 0 else ""
        self.rate_label.configure(text=f"{sign}{v}%")

    def _on_pitch_changed(self, _evt=None):
        v = int(round(float(self.pitch_scale.get())))
        self.pitch_var.set(v)
        sign = "+" if v >= 0 else ""
        self.pitch_label.configure(text=f"{sign}{v}Hz")

    def _on_drop(self, event):
        # Tk's drop event packages paths in a single space-separated string,
        # with curly braces around any path that contains spaces.
        raw = event.data
        paths: list[str] = []
        # Tk's tkdnd parses braces:
        i = 0
        while i < len(raw):
            if raw[i] == "{":
                end = raw.index("}", i)
                paths.append(raw[i + 1:end])
                i = end + 1
            elif raw[i] == " ":
                i += 1
            else:
                end = raw.find(" ", i)
                if end == -1:
                    paths.append(raw[i:])
                    break
                paths.append(raw[i:end])
                i = end + 1
        self._add_paths(paths)

    def _pick_files(self):
        types = [
            ("All supported", "*.txt *.md *.markdown *.docx *.pdf *.epub"),
            ("Text", "*.txt *.md *.markdown"),
            ("Word", "*.docx"),
            ("PDF", "*.pdf"),
            ("EPUB", "*.epub"),
            ("All files", "*.*"),
        ]
        picked = filedialog.askopenfilenames(title="Pick text files", filetypes=types)
        if picked:
            self._add_paths(list(picked))

    def _pick_folder(self):
        folder = filedialog.askdirectory(title="Pick a folder")
        if folder:
            self._add_paths([folder])

    def _add_paths(self, paths: list[str]):
        added = 0
        for p in paths:
            path = Path(p)
            if path.is_dir():
                # Recursive scan: include any supported file in or under this folder
                for sub in sorted(path.rglob("*")):
                    if sub.is_file() and sub.suffix.lower() in tts_lib.SUPPORTED_TEXT_EXTS:
                        if str(sub) not in self.files:
                            self.files.append(str(sub))
                            self.file_list.insert("end", str(sub))
                            added += 1
            elif path.is_file():
                if path.suffix.lower() not in tts_lib.SUPPORTED_TEXT_EXTS:
                    self._log(f"skipped (unsupported): {path.name}")
                    continue
                if str(path) not in self.files:
                    self.files.append(str(path))
                    self.file_list.insert("end", str(path))
                    added += 1
        if added:
            self._log(f"added {added} file(s)  (total: {len(self.files)})")

    def _remove_selected(self):
        sel = list(self.file_list.curselection())
        for idx in reversed(sel):
            self.file_list.delete(idx)
            del self.files[idx]

    def _clear(self):
        self.file_list.delete(0, "end")
        self.files.clear()

    def _pick_output(self):
        folder = filedialog.askdirectory(title="Pick an output folder")
        if folder:
            self.output_dir = Path(folder)
            self.output_var.set(folder)

    def _reset_output(self):
        self.output_dir = None
        self.output_var.set("(same folder as each source file)")

    def _on_convert(self):
        if self.worker.is_running():
            return
        if not self.files:
            messagebox.showinfo(APP_TITLE, "Add some files first.")
            return

        # Resolve voice
        voice_alias = self.voice_var.get()
        if voice_alias == "(custom)":
            voice = self.custom_voice_var.get().strip() or tts_lib.DEFAULT_VOICE
        else:
            voice = tts_lib.US_VOICES.get(voice_alias, tts_lib.DEFAULT_VOICE)

        rate_pct = int(round(float(self.rate_var.get())))
        rate = f"{'+' if rate_pct >= 0 else ''}{rate_pct}%"
        pitch_hz = int(round(float(self.pitch_var.get())))
        pitch = f"{'+' if pitch_hz >= 0 else ''}{pitch_hz}Hz"

        # Output language settings
        lang_mode = self.lang_var.get()  # 'english' | 'spanish' | 'both'
        es_voice = tts_lib.LATAM_SPANISH_VOICES.get(
            self.es_voice_var.get(), tts_lib.DEFAULT_SPANISH_VOICE,
        )
        save_translated = self.save_translated_text_var.get()

        files = list(self.files)
        self.progress.configure(maximum=len(files), value=0)
        self._log(
            f"--- starting {len(files)} file(s) — output={lang_mode} "
            f"en_voice={voice} es_voice={es_voice if lang_mode != 'english' else '-'} "
            f"rate={rate} pitch={pitch}"
        )
        self.go_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.worker.start(
            files, voice, rate, pitch,
            self.output_dir, self.force_var.get(),
            lang_mode=lang_mode,
            es_voice=es_voice,
            save_translated_text=save_translated,
        )

    def _on_cancel(self):
        if self.worker.is_running():
            self.worker.cancel()
            self._log("--- cancel requested; finishing current file then stopping...")

    # -- worker queue polling --

    def _on_worker_message(self, msg):
        # Called from worker thread — don't touch Tk here. The poll loop reads
        # directly from the queue instead.
        pass

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.worker.q.get_nowait()
                self._handle_message(kind, payload)
        except queue.Empty:
            pass
        self.root.after(80, self._poll_queue)

    def _handle_message(self, kind, payload):
        if kind == "progress":
            i, total, src, phase = payload["i"], payload["total"], payload["src"], payload["phase"]
            self.progress.configure(value=i - 1)
            self._log(f"[{i}/{total}] {phase}: {src}")
        elif kind == "ok":
            self.progress.step(1)
            self._log(f"  ✓ {payload}")
        elif kind == "skip":
            self.progress.step(1)
            self._log(f"  skip: {payload}")
        elif kind == "error":
            self.progress.step(1)
            self._log(f"  ! {payload}")
        elif kind == "cancelled":
            self._log("--- cancelled")
        elif kind == "done":
            self._log("--- done")
            self.go_btn.configure(state="normal")
            self.cancel_btn.configure(state="disabled")
            self.progress.configure(value=self.progress.cget("maximum"))

    # -- helpers --

    def _log(self, msg: str):
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def run(self):
        self.root.mainloop()


def main() -> int:
    try:
        App().run()
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
