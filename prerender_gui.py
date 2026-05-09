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
        self.root.minsize(580, 500)

        self._set_window_icon()
        self._apply_theme()

        self.files: list[str] = []
        self.output_dir: Path | None = None
        self.worker = _Worker(on_message=self._on_worker_message)

        self._build_ui()
        # Size the window to fit the whole interface, or the screen height,
        # whichever is smaller. Has to run AFTER _build_ui so every widget
        # has reported its requested size to Tk's geometry manager.
        self._size_to_content()
        self._poll_queue()

    def _size_to_content(self):
        """Open the window at min(natural-content-height, available-screen-height).
        The natural width is what _build_ui asks for, clamped to a sane minimum.
        Position roughly centered horizontally and a little down from the top."""
        self.root.update_idletasks()
        # winfo_reqwidth/reqheight = the size the layout would prefer
        want_w = max(self.root.winfo_reqwidth(), 700)
        want_h = self.root.winfo_reqheight()
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        # Leave headroom for the OS title bar + taskbar so the window
        # isn't flush with the screen edge.
        safe_h = screen_h - 100
        safe_w = screen_w - 60
        w = min(max(want_w, 580), safe_w)
        h = min(max(want_h, 500), safe_h)
        x = (screen_w - w) // 2
        y = max(20, (screen_h - h) // 4)
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def _set_window_icon(self):
        """Set the Tk window's title-bar / taskbar icon to the same headphones
        glyph the Android PWA uses. Tries the .ico first (best on Windows;
        carries multiple resolutions in one file), falls back to the 192-px
        PNG via iconphoto for other platforms.

        When packaged as a PyInstaller --onefile exe the resources live in
        sys._MEIPASS/icons rather than next to the script, so we check both
        paths."""
        try:
            base_candidates = [Path(__file__).parent]
            mei = getattr(sys, "_MEIPASS", None)
            if mei:
                base_candidates.insert(0, Path(mei))

            for base in base_candidates:
                ico = base / "icons" / "headphones.ico"
                if ico.exists():
                    self.root.iconbitmap(default=str(ico))
                    return
            for base in base_candidates:
                png = base / "icons" / "headphones-192.png"
                if png.exists():
                    self._icon_img = tk.PhotoImage(file=str(png))
                    self.root.iconphoto(True, self._icon_img)
                    return
        except Exception:
            pass  # silently no-op if we can't locate or load the icon

    def _apply_theme(self):
        """Apply a dark theme matching the Spanish Trainer / Audio Player
        visual language: layered near-black surfaces, amber accent, muted
        text hierarchy, uppercase title chips. Tkinter doesn't do CSS so
        every widget class needs explicit ttk.Style configuration plus
        manual bg/fg on the few raw tk widgets (Listbox, Text)."""
        # Color tokens — match spanish_app/index.html :root values
        T = {
            'bg':         '#0a0a0d',
            'bg_card':    '#16161d',
            'bg_tile':    '#1c1c25',
            'bg_input':   '#1f1f29',
            'bg_hover':   '#23232f',
            'border':     '#26262f',
            'border_soft':'#1e1e26',
            'text':       '#ededf0',
            'text_mid':   '#a8a8b3',
            'text_dim':   '#6a6a76',
            'accent':     '#fbbf24',
            'accent_hi':  '#fcd34d',
            'accent_ink': '#1a1004',
            'good':       '#34d399',
            'bad':        '#f87171',
        }
        self._theme = T
        self._mono_font = ('Consolas', 9)
        self._ui_font = ('Segoe UI', 10)
        self._title_font = ('Segoe UI', 9, 'bold')

        self.root.configure(bg=T['bg'])

        style = ttk.Style()
        # 'clam' is the most customizable built-in theme on Windows; the
        # native 'vista' / 'xpnative' themes ignore many color overrides.
        try: style.theme_use('clam')
        except Exception: pass

        # Frame styles — default is the page background, Card variant is
        # used for the inner content of LabelFrame cards
        style.configure('TFrame',       background=T['bg'])
        style.configure('Card.TFrame',  background=T['bg_card'])

        # Labels follow the surface they're on
        style.configure('TLabel',       background=T['bg'],
                                        foreground=T['text'], font=self._ui_font)
        style.configure('Card.TLabel',  background=T['bg_card'],
                                        foreground=T['text'], font=self._ui_font)
        style.configure('Dim.TLabel',   background=T['bg_card'],
                                        foreground=T['text_dim'], font=self._ui_font)
        style.configure('Hint.TLabel',  background=T['bg_card'],
                                        foreground=T['text_dim'],
                                        font=('Segoe UI', 8, 'italic'))

        # LabelFrame (the cards). The 'labelmargins' make the title chip
        # sit slightly inset.
        style.configure('TLabelframe', background=T['bg_card'],
                        bordercolor=T['border_soft'], lightcolor=T['border_soft'],
                        darkcolor=T['border_soft'], borderwidth=1, relief='solid')
        style.configure('TLabelframe.Label', background=T['bg_card'],
                        foreground=T['text_dim'], font=self._title_font,
                        padding=(6, 0))

        # Default chip-style button
        style.configure('TButton',
                        background=T['bg_tile'], foreground=T['text'],
                        bordercolor=T['border'], lightcolor=T['border'],
                        darkcolor=T['border'], focuscolor='none',
                        padding=(10, 6), font=self._ui_font, relief='flat')
        style.map('TButton',
                  background=[('active', T['bg_hover']), ('pressed', T['bg_hover'])],
                  bordercolor=[('focus', T['accent'])])

        # Primary call-to-action button (Convert all)
        style.configure('Accent.TButton',
                        background=T['accent'], foreground=T['accent_ink'],
                        bordercolor=T['accent'], lightcolor=T['accent'],
                        darkcolor=T['accent'], focuscolor='none',
                        padding=(14, 8), font=('Segoe UI', 10, 'bold'),
                        relief='flat')
        style.map('Accent.TButton',
                  background=[('active', T['accent_hi']), ('pressed', T['accent_hi'])],
                  foreground=[('active', T['accent_ink'])])

        # Checkbutton / Radiobutton — sit on cards
        for klass in ('TCheckbutton', 'TRadiobutton'):
            style.configure(klass,
                            background=T['bg_card'], foreground=T['text'],
                            focuscolor='none', font=self._ui_font,
                            indicatorbackground=T['bg_input'],
                            indicatorforeground=T['accent'])
            style.map(klass,
                      background=[('active', T['bg_card'])],
                      indicatorcolor=[('selected', T['accent']),
                                      ('!selected', T['bg_input'])])

        # Combobox (dropdowns)
        style.configure('TCombobox',
                        fieldbackground=T['bg_input'],
                        background=T['bg_tile'],
                        foreground=T['text'],
                        bordercolor=T['border'],
                        lightcolor=T['border'], darkcolor=T['border'],
                        arrowcolor=T['text_mid'],
                        selectbackground=T['bg_input'],
                        selectforeground=T['text'],
                        padding=(6, 4), font=self._ui_font)
        style.map('TCombobox',
                  fieldbackground=[('readonly', T['bg_input'])],
                  bordercolor=[('focus', T['accent'])],
                  arrowcolor=[('active', T['text'])])
        # The Combobox's dropdown listbox is a tk Listbox under the hood;
        # only option_add reaches it.
        self.root.option_add('*TCombobox*Listbox.background', T['bg_tile'])
        self.root.option_add('*TCombobox*Listbox.foreground', T['text'])
        self.root.option_add('*TCombobox*Listbox.selectBackground', T['accent'])
        self.root.option_add('*TCombobox*Listbox.selectForeground', T['accent_ink'])
        self.root.option_add('*TCombobox*Listbox.borderWidth', '0')
        self.root.option_add('*TCombobox*Listbox.font', self._ui_font)

        # Entry
        style.configure('TEntry',
                        fieldbackground=T['bg_input'],
                        foreground=T['text'],
                        bordercolor=T['border'],
                        lightcolor=T['border'], darkcolor=T['border'],
                        insertcolor=T['accent'], font=self._ui_font)
        style.map('TEntry', bordercolor=[('focus', T['accent'])])

        # Scale (sliders)
        style.configure('Horizontal.TScale',
                        background=T['bg_card'],
                        troughcolor=T['border'],
                        bordercolor=T['border_soft'],
                        sliderthickness=14)

        # Progressbar
        style.configure('Horizontal.TProgressbar',
                        background=T['accent'],
                        troughcolor=T['border'],
                        bordercolor=T['border_soft'],
                        lightcolor=T['accent'], darkcolor=T['accent'])

        # Scrollbar
        style.configure('Vertical.TScrollbar',
                        background=T['bg_tile'],
                        troughcolor=T['bg'],
                        bordercolor=T['bg'],
                        arrowcolor=T['text_dim'],
                        gripcount=0, relief='flat')
        style.map('Vertical.TScrollbar',
                  background=[('active', T['bg_hover'])])

    # -- UI construction --

    def _build_ui(self):
        pad = {"padx": 12, "pady": 6}
        T = self._theme

        # Header
        header = ttk.Frame(self.root)
        header.pack(fill="x", padx=12, pady=(12, 8))
        ttk.Label(
            header, text=APP_TITLE,
            font=("Segoe UI", 15, "bold"),
            background=T['bg'], foreground=T['text'],
        ).pack(side="left")
        ttk.Label(
            header,
            text="Convert .txt / .md / .docx / .pdf / .epub  →  .mp3",
            background=T['bg'], foreground=T['text_dim'],
            font=("Segoe UI", 9),
        ).pack(side="left", padx=(12, 0))

        # Files list with drop target
        files_frame = ttk.LabelFrame(self.root, text="Files to convert")
        files_frame.pack(fill="both", expand=True, **pad)

        list_wrap = ttk.Frame(files_frame, style='Card.TFrame')
        list_wrap.pack(fill="both", expand=True, padx=10, pady=(10, 0))
        scroll = ttk.Scrollbar(list_wrap, orient="vertical")
        scroll.pack(side="right", fill="y")
        self.file_list = tk.Listbox(
            list_wrap, yscrollcommand=scroll.set,
            selectmode="extended", activestyle="none",
            bg=T['bg_tile'], fg=T['text'],
            selectbackground=T['accent'], selectforeground=T['accent_ink'],
            borderwidth=0, highlightthickness=0,
            font=self._ui_font,
        )
        self.file_list.pack(side="left", fill="both", expand=True)
        scroll.config(command=self.file_list.yview)

        if _HAS_DND:
            self.file_list.drop_target_register(DND_FILES)
            self.file_list.dnd_bind("<<Drop>>", self._on_drop)

        btns = ttk.Frame(files_frame, style='Card.TFrame')
        btns.pack(fill="x", padx=10, pady=10)
        ttk.Button(btns, text="Add files…", command=self._pick_files).pack(side="left")
        ttk.Button(btns, text="Add folder…", command=self._pick_folder).pack(side="left", padx=(6, 0))
        ttk.Button(btns, text="Remove selected", command=self._remove_selected).pack(side="left", padx=(6, 0))
        ttk.Button(btns, text="Clear", command=self._clear).pack(side="left", padx=(6, 0))
        if _HAS_DND:
            ttk.Label(
                btns,
                text="tip: drag files or folders onto the list",
                background=T['bg_card'], foreground=T['text_dim'],
                font=("Segoe UI", 8, "italic"),
            ).pack(side="right")

        # Settings
        settings = ttk.LabelFrame(self.root, text="Voice & pacing")
        settings.pack(fill="x", **pad)

        row1 = ttk.Frame(settings, style='Card.TFrame'); row1.pack(fill="x", padx=10, pady=6)
        ttk.Label(row1, text="Voice:", width=10, style='Card.TLabel').pack(side="left")
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

        row2 = ttk.Frame(settings, style='Card.TFrame'); row2.pack(fill="x", padx=10, pady=6)
        ttk.Label(row2, text="Rate:", width=10, style='Card.TLabel').pack(side="left")
        self.rate_var = tk.IntVar(value=-5)
        self.rate_scale = ttk.Scale(
            row2, from_=-30, to=30, orient="horizontal",
            variable=self.rate_var, command=self._on_rate_changed,
        )
        self.rate_scale.pack(side="left", fill="x", expand=True)
        self.rate_label = ttk.Label(row2, text="-5%", width=6, anchor="e",
                                    style='Card.TLabel')
        self.rate_label.pack(side="left", padx=(8, 0))

        row3 = ttk.Frame(settings, style='Card.TFrame'); row3.pack(fill="x", padx=10, pady=6)
        ttk.Label(row3, text="Pitch:", width=10, style='Card.TLabel').pack(side="left")
        self.pitch_var = tk.IntVar(value=0)
        self.pitch_scale = ttk.Scale(
            row3, from_=-20, to=20, orient="horizontal",
            variable=self.pitch_var, command=self._on_pitch_changed,
        )
        self.pitch_scale.pack(side="left", fill="x", expand=True)
        self.pitch_label = ttk.Label(row3, text="+0Hz", width=6, anchor="e",
                                     style='Card.TLabel')
        self.pitch_label.pack(side="left", padx=(8, 0))

        row4 = ttk.Frame(settings, style='Card.TFrame'); row4.pack(fill="x", padx=10, pady=6)
        ttk.Label(row4, text="Output:", width=10, style='Card.TLabel').pack(side="left")
        self.output_var = tk.StringVar(value="(same folder as each source file)")
        ttk.Entry(row4, textvariable=self.output_var, state="readonly").pack(
            side="left", fill="x", expand=True,
        )
        ttk.Button(row4, text="Pick…", command=self._pick_output).pack(side="left", padx=(6, 0))
        ttk.Button(row4, text="Reset", command=self._reset_output).pack(side="left", padx=(4, 0))

        row5 = ttk.Frame(settings, style='Card.TFrame'); row5.pack(fill="x", padx=10, pady=(6, 10))
        self.force_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            row5, text="Re-render even if .mp3 already exists",
            variable=self.force_var,
        ).pack(side="left")

        # Output language (English / Spanish translation / Both)
        lang_frame = ttk.LabelFrame(self.root, text="Output language")
        lang_frame.pack(fill="x", **pad)

        rowL1 = ttk.Frame(lang_frame, style='Card.TFrame'); rowL1.pack(fill="x", padx=10, pady=6)
        ttk.Label(rowL1, text="Output:", width=10, style='Card.TLabel').pack(side="left")
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

        rowL2 = ttk.Frame(lang_frame, style='Card.TFrame'); rowL2.pack(fill="x", padx=10, pady=6)
        ttk.Label(rowL2, text="Spanish voice:", width=14, style='Card.TLabel').pack(side="left")
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
            style='Dim.TLabel',
        )
        self.es_voice_hint.pack(side="left", padx=(8, 0))

        rowL3 = ttk.Frame(lang_frame, style='Card.TFrame'); rowL3.pack(fill="x", padx=10, pady=6)
        self.save_translated_text_var = tk.BooleanVar(value=True)
        self.save_translated_text_chk = ttk.Checkbutton(
            rowL3,
            text="Also save the translated text as .es.txt  (pairs with the .es.mp3 in the audio player)",
            variable=self.save_translated_text_var,
        )
        self.save_translated_text_chk.pack(side="left")

        rowL4 = ttk.Frame(lang_frame, style='Card.TFrame'); rowL4.pack(fill="x", padx=10, pady=(0, 10))
        self.lang_note = ttk.Label(
            rowL4,
            text="(Translation uses Google's free unofficial endpoint — needs internet at convert time.)",
            style='Hint.TLabel',
        )
        self.lang_note.pack(side="left")

        # Sync the visibility of the Spanish-only controls
        self._on_lang_changed()

        # Action bar — primary CTA uses the amber accent style
        actions = ttk.Frame(self.root)
        actions.pack(fill="x", **pad)
        self.go_btn = ttk.Button(
            actions, text="Convert all", command=self._on_convert,
            style='Accent.TButton',
        )
        self.go_btn.pack(side="left")
        self.cancel_btn = ttk.Button(
            actions, text="Cancel", command=self._on_cancel, state="disabled",
        )
        self.cancel_btn.pack(side="left", padx=(8, 0))
        self.progress = ttk.Progressbar(actions, mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True, padx=(12, 0))

        # Log
        log_frame = ttk.LabelFrame(self.root, text="Log")
        log_frame.pack(fill="both", expand=True, **pad)
        self.log = tk.Text(
            log_frame, height=8, state="disabled", wrap="none",
            bg=T['bg_tile'], fg=T['text_mid'],
            insertbackground=T['accent'],
            selectbackground=T['accent'], selectforeground=T['accent_ink'],
            borderwidth=0, highlightthickness=0,
            font=self._mono_font,
        )
        self.log.pack(fill="both", expand=True, padx=10, pady=10)

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
        T = self._theme
        state = "readonly" if es_active else "disabled"
        self.es_voice_combo.configure(state=state)
        self.es_voice_hint.configure(
            foreground=(T['text_dim'] if es_active else T['border']),
        )
        chk_state = "normal" if es_active else "disabled"
        self.save_translated_text_chk.configure(state=chk_state)
        self.lang_note.configure(
            foreground=(T['text_dim'] if es_active else T['border']),
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
