"""Image-to-Art and Animation-to-Art workspaces for the Tk desktop edition.

Both workspaces share the application's export engine, settings manager (presets, favourite palettes),
colour/effects engines and project format. Rendering runs on a "latest job only" worker thread.
"""
from __future__ import annotations

import io
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from ..effects import apply_effects
from ..export import FORMATS, ExportSettings, export_bytes, render_image, to_ansi, to_txt
from ..imgcore import ImageDecodeError, clipboard_image, decode_frames, decode_image, decoder_capabilities
from ..imgglyphs import PALETTES, export_palettes, import_palettes, palette_from_figlet, sort_by_density
from ..imgmodes import (IMG_PARAMS, MODES, P_CHOICES, RenderCancelled, estimate_cost, prepare,
                        render_image_art, sanitize_params)
from ..imganalysis import OPT_PRESETS, analyze, optimize, recommended_params
from ..imganim import (batch_convert, comparison_png, compose_typographic, composition_png, composition_svg,
                       convert_animation, make_image_project, parse_image_project, to_animated_html, to_ansi_script,
                       to_frame_zip, to_gif)
from ..project import atomic_write

COL_PRESETS = ["40", "80", "120", "200", "300", "500", "1000"]
ADJUST_KEYS = ["exposure", "brightness", "contrast", "gamma", "saturation", "vibrance", "hue", "sharpness", "blur",
               "denoise", "black", "white", "highlights", "shadows", "posterize", "local_contrast", "remove_bg"]
LABELS = {
    "cols": "Width (chars)", "rows": "Height (0 = auto)", "cell_aspect": "Cell aspect w/h", "lock_aspect": "Lock aspect",
    "target_aspect": "Custom aspect (0 = image)", "fit": "Fit", "crop_x0": "Crop left", "crop_y0": "Crop top",
    "crop_x1": "Crop right", "crop_y1": "Crop bottom", "rotate": "Rotate 90°", "angle": "Rotate (free °)",
    "flip_h": "Flip horizontal", "flip_v": "Flip vertical", "pad": "Padding", "remove_bg": "Remove background",
    "local_contrast": "Local contrast", "equalize": "Histogram equalization", "palette_reverse": "Reverse density",
    "dither_strength": "Dither strength", "threshold": "Threshold / dot sensitivity", "adaptive": "Adaptive threshold",
    "edge_method": "Edge method", "edge_strength": "Edge strength", "edge_threshold": "Edge threshold",
    "levels": "Contour levels", "luma": "Luminance", "light_on_dark": "Light text on dark", "color": "Colour mode",
    "colors": "Custom colours", "gradient": "Gradient stops", "dominant_k": "Dominant colours",
    "color_target": "Colour target", "background": "Background", "transparent_bg": "Keep transparency empty",
    "text": "Text / words", "text_mode": "Word layout", "text_dir": "Direction", "seed": "Random seed",
}
SECTIONS = [
    ("ALGORITHM", ["luma", "dither", "dither_strength", "threshold", "adaptive", "light_on_dark", "seed"]),
    ("CUSTOM WORDS", ["text", "text_mode", "text_dir"]),
    ("OUTPUT RESOLUTION", ["cols", "rows", "cell_aspect", "lock_aspect", "target_aspect", "fit"]),
    ("GEOMETRY", ["crop_x0", "crop_y0", "crop_x1", "crop_y1", "rotate", "angle", "flip_h", "flip_v", "pad"]),
    ("IMAGE ADJUSTMENTS", ADJUST_KEYS + ["equalize", "grayscale", "invert"]),
    ("EDGES", ["edge_method", "edge_strength", "edge_threshold", "levels"]),
    ("COLOURS & BACKGROUND", ["color", "colors", "gradient", "dominant_k", "color_target", "background", "transparent_bg"]),
]


def _fmt_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


class _Worker(threading.Thread):
    """Latest-job-only background worker with a cancellation flag for the running job."""

    def __init__(self, results: queue.Queue):
        super().__init__(daemon=True)
        self.results, self.cv, self.job, self.cancel_gen = results, threading.Condition(), None, -1

    def submit(self, tag, gen, fn):
        with self.cv:
            self.job = (tag, gen, fn)
            self.cv.notify()

    def run(self):
        while True:
            with self.cv:
                while self.job is None:
                    self.cv.wait()
                (tag, gen, fn), self.job = self.job, None
            t0 = time.perf_counter()
            try:
                res, err = fn(), None
            except Exception as exc:  # noqa: BLE001 - shown in the UI
                res, err = None, exc
            self.results.put((tag, gen, res, err, time.perf_counter() - t0))


class _Base(ttk.Frame):
    """Shared plumbing: param variables, canvas preview with zoom/pan, status line."""

    def __init__(self, parent, app, colors):
        super().__init__(parent, style="Bg0.TFrame")
        self.app, self.C = app, colors
        self.results: queue.Queue = queue.Queue()
        self.worker = _Worker(self.results)
        self.worker.start()
        self.gen = 0
        self.zoom = 1.0
        self.photo = None
        self.after(60, self._poll)

    def _scroll(self, parent):
        cv = tk.Canvas(parent, bg=self.C["bg1"], highlightthickness=0, width=330)
        sb = ttk.Scrollbar(parent, command=cv.yview)
        inner = ttk.Frame(cv, padding=(8, 4))
        inner.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
        win = cv.create_window(0, 0, window=inner, anchor="nw")
        cv.bind("<Configure>", lambda e: cv.itemconfigure(win, width=e.width))
        cv.configure(yscrollcommand=sb.set)
        cv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        inner.bind("<Enter>", lambda e: cv.bind_all("<MouseWheel>", lambda ev: cv.yview_scroll(int(-ev.delta / 60), "units")))
        inner.bind("<Leave>", lambda e: cv.unbind_all("<MouseWheel>"))
        return inner

    def _head(self, parent, text):
        ttk.Label(parent, text=text, style="Head.TLabel").pack(anchor="w", pady=(10, 3))

    def fix_sash(self):
        p = getattr(self, "_paned", None)
        if p is None:
            return
        self.update_idletasks()
        w = self.winfo_width()
        if w < 200:
            self.after(80, self.fix_sash)
            return
        try:
            p.sashpos(0, 300)
            p.sashpos(1, max(600, w - 370))
        except tk.TclError:
            pass

    def _poll(self):
        try:
            while True:
                tag, gen, res, err, dt = self.results.get_nowait()
                self.on_result(tag, gen, res, err, dt)
        except queue.Empty:
            pass
        self.after(50, self._poll)

    def on_result(self, tag, gen, res, err, dt):  # overridden
        pass

    def export_settings(self) -> ExportSettings:
        return self.app._read_export_settings()

    def ask_save(self, title, ext, data: bytes):
        path = filedialog.asksaveasfilename(parent=self, title=title, defaultextension=ext,
                                            filetypes=[(ext.upper().strip("."), "*" + ext), ("All files", "*.*")])
        if path:
            atomic_write(path, data)
            self.set_status(f"Saved {os.path.basename(path)} ({_fmt_bytes(len(data))})")

    def set_status(self, msg):
        self.status_var.set(msg)


# ======================================================================= Image Studio
class ImageWorkspace(_Base):
    def __init__(self, parent, app, colors):
        super().__init__(parent, app, colors)
        self.library: list[dict] = []          # {name, data(bytes), img}
        self.current = -1
        self.vars: dict[str, tk.Variable] = {}
        self.params = sanitize_params(app.settings.data.get("image_last") or {})
        self.undo: list[dict] = []
        self.redo: list[dict] = []
        self.art = None
        self.stats = {}
        self.art_img = None      # PIL image of the rendered art
        self.src_img = None      # PIL image of the source (or adjusted source)
        self.view = tk.StringVar(value="art")
        self.slider = 0.5
        self.show_adjusted = tk.BooleanVar(value=False)
        self.show_grid = tk.BooleanVar(value=False)
        self.apply_fx = tk.BooleanVar(value=False)
        self.fmt = tk.StringVar(value="txt")
        self._debounce = None
        self._suspend = False
        self._build()
        self._load_vars()

    # ------------------------------------------------------------- layout
    def _build(self):
        paned = ttk.Panedwindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True)
        left = ttk.Frame(paned, padding=(10, 8))
        center = ttk.Frame(paned, style="Bg0.TFrame", padding=(8, 8))
        right = ttk.Frame(paned, padding=(4, 8))
        paned.add(left, weight=0)
        paned.add(center, weight=1)
        paned.add(right, weight=0)
        self._paned = paned
        self._build_left(left)
        self._build_center(center)
        self._build_right(right)
        bar = ttk.Frame(self, style="Bg0.TFrame", padding=(14, 3))
        bar.pack(fill="x")
        self.status_var = tk.StringVar(value="Open or paste an image (Ctrl+V). Everything is processed locally.")
        ttk.Label(bar, textvariable=self.status_var, style="Bar.TLabel").pack(side="left")
        self.info_var = tk.StringVar()
        ttk.Label(bar, textvariable=self.info_var, style="Bar.TLabel").pack(side="right")

    def _build_left(self, p):
        self._head(p, "IMAGE IMPORT")
        r = ttk.Frame(p); r.pack(fill="x")
        ttk.Button(r, text="Open…", command=self.open_images).pack(side="left")
        ttk.Button(r, text="Paste", command=self.paste_image).pack(side="left", padx=4)
        ttk.Button(r, text="Remove", command=self.remove_image).pack(side="left")
        ttk.Label(p, text="Formats: " + ", ".join(k for k, v in decoder_capabilities()["formats"].items() if v is True),
                  style="Muted.TLabel", wraplength=240).pack(anchor="w", pady=(3, 0))
        self._head(p, "IMAGE LIBRARY / BATCH QUEUE")
        self.lib_list = tk.Listbox(p, height=6, bg=self.C["bg2"], fg=self.C["text"], selectbackground=self.C["sel"],
                                   highlightthickness=0, borderwidth=0, exportselection=False)
        self.lib_list.pack(fill="x")
        self.lib_list.bind("<<ListboxSelect>>", lambda e: self._select_image())
        ttk.Button(p, text="Batch export queue…", command=self.batch_export).pack(fill="x", pady=(4, 0))
        self._head(p, "CONVERSION MODE")
        mf = ttk.Frame(p); mf.pack(fill="both", expand=True)
        self.mode_list = tk.Listbox(mf, height=12, bg=self.C["bg2"], fg=self.C["text"], selectbackground=self.C["sel"],
                                    highlightthickness=0, borderwidth=0, exportselection=False)
        sb = ttk.Scrollbar(mf, command=self.mode_list.yview)
        self.mode_list.configure(yscrollcommand=sb.set)
        self.mode_list.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        for k, m in MODES.items():
            self.mode_list.insert("end", f"{m[0]}")
        self.mode_list.bind("<<ListboxSelect>>", lambda e: self._mode_selected())
        self.mode_desc = ttk.Label(p, text="", style="Muted.TLabel", wraplength=240)
        self.mode_desc.pack(anchor="w", pady=(3, 0))
        self._head(p, "CHARACTER PALETTE")
        self.pal_var = tk.StringVar()
        names = [""] + list(PALETTES) + [f"★ {d['name']}" for d in self.app.settings.data.get("palettes", [])]
        self.pal_combo = ttk.Combobox(p, textvariable=self.pal_var, values=names)
        self.pal_combo.pack(fill="x")
        self.pal_combo.bind("<<ComboboxSelected>>", lambda e: self._palette_chosen())
        self.pal_combo.bind("<Return>", lambda e: self._palette_chosen())
        r = ttk.Frame(p); r.pack(fill="x", pady=(3, 0))
        for label, cmd in (("Sort", self.sort_palette), ("★ Save", self.save_palette), ("From font", self.palette_from_font)):
            ttk.Button(r, text=label, style="Tool.TButton", command=cmd).pack(side="left", padx=(0, 3))
        r = ttk.Frame(p); r.pack(fill="x", pady=(3, 0))
        ttk.Button(r, text="Import…", style="Tool.TButton", command=self.import_palette).pack(side="left", padx=(0, 3))
        ttk.Button(r, text="Export…", style="Tool.TButton", command=self.export_palette).pack(side="left")
        self.vars["palette_reverse"] = tk.BooleanVar()
        ttk.Checkbutton(p, text="Reverse density", variable=self.vars["palette_reverse"],
                        command=self._changed).pack(anchor="w")
        self._head(p, "SAVED PRESETS")
        self.preset_var = tk.StringVar()
        self.preset_combo = ttk.Combobox(p, textvariable=self.preset_var, values=sorted(self.app.settings.data["image_presets"]))
        self.preset_combo.pack(fill="x")
        r = ttk.Frame(p); r.pack(fill="x", pady=(3, 0))
        for label, cmd in (("Load", self.load_preset), ("Save", self.save_preset), ("Delete", self.delete_preset)):
            ttk.Button(r, text=label, style="Tool.TButton", command=cmd).pack(side="left", padx=(0, 3))

    def _build_center(self, p):
        tb = ttk.Frame(p, style="Bg0.TFrame")
        tb.pack(fill="x")
        for key, label in (("art", "Text art"), ("original", "Original"), ("side", "Side by side"),
                           ("slider", "Slider"), ("split", "Split")):
            ttk.Radiobutton(tb, text=label, value=key, variable=self.view, command=self.redraw,
                            style="Bar.TCheckbutton").pack(side="left", padx=2)
        ttk.Checkbutton(tb, text="Adjusted", variable=self.show_adjusted, command=self._source_changed,
                        style="Bar.TCheckbutton").pack(side="left", padx=6)
        ttk.Checkbutton(tb, text="Grid", variable=self.show_grid, command=self.redraw, style="Bar.TCheckbutton").pack(side="left")
        for label, cmd in (("⛶", self.fullscreen), ("Fit", self.fit), ("+", lambda: self.set_zoom(self.zoom * 1.25)),
                           ("−", lambda: self.set_zoom(self.zoom / 1.25))):
            ttk.Button(tb, text=label, style="Tool.TButton", command=cmd).pack(side="right", padx=1)
        self.zoom_lbl = ttk.Label(tb, text="100%", style="Bar.TLabel")
        self.zoom_lbl.pack(side="right", padx=6)
        tb2 = ttk.Frame(p, style="Bg0.TFrame")
        tb2.pack(fill="x", pady=(4, 4))
        ttk.Button(tb2, text="Analyze image", command=self.run_analyze).pack(side="left")
        ttk.Label(tb2, text="  Smart Optimize:", style="Bar.TLabel").pack(side="left")
        self.opt_var = tk.StringVar(value="similarity")
        ttk.Combobox(tb2, textvariable=self.opt_var, values=list(OPT_PRESETS), state="readonly", width=12).pack(side="left", padx=4)
        ttk.Button(tb2, text="Run", command=self.run_optimize).pack(side="left")
        for label, cmd in (("Redo", self.do_redo), ("Undo", self.do_undo), ("Reset", self.reset_params)):
            ttk.Button(tb2, text=label, style="Tool.TButton", command=cmd).pack(side="right", padx=1)
        self.canvas = tk.Canvas(p, bg="#05060a", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self.redraw())
        self.canvas.bind("<ButtonPress-3>", lambda e: self.canvas.scan_mark(e.x, e.y))
        self.canvas.bind("<B3-Motion>", lambda e: self.canvas.scan_dragto(e.x, e.y, gain=1))
        self.canvas.bind("<ButtonPress-2>", lambda e: self.canvas.scan_mark(e.x, e.y))
        self.canvas.bind("<B2-Motion>", lambda e: self.canvas.scan_dragto(e.x, e.y, gain=1))
        self.canvas.bind("<B1-Motion>", self._drag_slider)
        self.canvas.bind("<Button-1>", self._drag_slider)
        self.canvas.bind("<Control-MouseWheel>", lambda e: self.set_zoom(self.zoom * (1.15 if e.delta > 0 else 1 / 1.15)))
        ttk.Label(p, text="Right-drag to pan · Ctrl+wheel to zoom · drag in Slider view to compare", style="Bar.TLabel").pack(anchor="w")

    def _build_right(self, p):
        inner = self._scroll(p)
        for title, keys in SECTIONS:
            self._head(inner, title)
            f = ttk.Frame(inner)
            f.pack(fill="x")
            f.columnconfigure(1, weight=1)
            for r, key in enumerate(keys):
                self._param_widget(f, r, key)
            if title == "OUTPUT RESOLUTION":
                r = len(keys)
                ttk.Label(f, text="Preset", style="Muted.TLabel").grid(row=r, column=0, sticky="w")
                cp = ttk.Combobox(f, values=COL_PRESETS + ["custom"], width=8, state="readonly")
                cp.grid(row=r, column=1, sticky="ew", pady=2)
                cp.bind("<<ComboboxSelected>>", lambda e, w=cp: self._col_preset(w.get()))
                self.ls_var = tk.DoubleVar(value=self.app.exp.letter_spacing)
                self.lh_var = tk.DoubleVar(value=self.app.exp.line_height)
                for k2, (lbl, var, lo, hi) in enumerate((("Char spacing", self.ls_var, 0, 2), ("Line spacing", self.lh_var, 0.8, 3))):
                    ttk.Label(f, text=lbl, style="Muted.TLabel").grid(row=r + 1 + k2, column=0, sticky="w")
                    ttk.Spinbox(f, from_=lo, to=hi, increment=0.05, textvariable=var, width=8,
                                command=self._spacing).grid(row=r + 1 + k2, column=1, sticky="ew", pady=2)
                self.cost_lbl = ttk.Label(f, text="", style="Muted.TLabel", wraplength=280)
                self.cost_lbl.grid(row=r + 3, column=0, columnspan=2, sticky="w")
        self._head(inner, "EFFECTS (SHARED WITH TEXT STUDIO)")
        ttk.Checkbutton(inner, text="Apply the Text Studio effects pipeline", variable=self.apply_fx,
                        command=self._changed).pack(anchor="w")
        self._head(inner, "EXPORT")
        f = ttk.Frame(inner); f.pack(fill="x")
        ttk.Combobox(f, textvariable=self.fmt, values=list(FORMATS), state="readonly", width=8).pack(side="left")
        ttk.Button(f, text="Export…", style="Accent.TButton", command=self.export_art).pack(side="left", padx=4)
        f = ttk.Frame(inner); f.pack(fill="x", pady=(4, 0))
        ttk.Button(f, text="Copy text", style="Tool.TButton", command=lambda: self.copy("text")).pack(side="left")
        ttk.Button(f, text="Copy ANSI", style="Tool.TButton", command=lambda: self.copy("ansi")).pack(side="left", padx=3)
        ttk.Button(f, text="Comparison PNG…", style="Tool.TButton", command=self.export_comparison).pack(side="left")
        ttk.Label(inner, text="Export settings (font size, colours, scale, transparency) come from the Text Studio "
                              "Export tab.", style="Muted.TLabel", wraplength=300).pack(anchor="w", pady=(3, 0))
        self._head(inner, "TYPOGRAPHIC COMPOSITION (GRAPHIC, NOT TEXT)")
        f = ttk.Frame(inner); f.pack(fill="x")
        self.typo_size = tk.DoubleVar(value=10)
        self.typo_vary = tk.StringVar(value="opacity")
        self.typo_rot = tk.IntVar(value=0)
        ttk.Spinbox(f, from_=4, to=64, textvariable=self.typo_size, width=5).pack(side="left")
        ttk.Combobox(f, textvariable=self.typo_vary, values=["opacity", "size", "weight"], state="readonly", width=8).pack(side="left", padx=3)
        ttk.Checkbutton(f, text="90°", variable=self.typo_rot, onvalue=90, offvalue=0).pack(side="left")
        f = ttk.Frame(inner); f.pack(fill="x", pady=(3, 0))
        ttk.Button(f, text="PNG…", style="Tool.TButton", command=lambda: self.export_typo("png")).pack(side="left")
        ttk.Button(f, text="SVG…", style="Tool.TButton", command=lambda: self.export_typo("svg")).pack(side="left", padx=3)
        self._head(inner, "PROJECT")
        f = ttk.Frame(inner); f.pack(fill="x")
        ttk.Button(f, text="Save image project…", style="Tool.TButton", command=self.save_project).pack(side="left")
        ttk.Button(f, text="Open…", style="Tool.TButton", command=self.open_project).pack(side="left", padx=3)
        self.compat_lbl = ttk.Label(inner, text="", style="Muted.TLabel", wraplength=300)
        self.compat_lbl.pack(anchor="w", pady=(10, 20))

    def _param_widget(self, f, r, key):
        spec = IMG_PARAMS[key]
        t = spec[0]
        ttk.Label(f, text=LABELS.get(key, key.replace("_", " ").capitalize()), style="Muted.TLabel").grid(
            row=r, column=0, sticky="w", pady=1, padx=(0, 6))
        if t == "bool":
            v = tk.BooleanVar()
            w = ttk.Checkbutton(f, variable=v, command=self._changed)
        elif t == "choice":
            v = tk.StringVar()
            w = ttk.Combobox(f, textvariable=v, values=[str(c) for c in P_CHOICES[key]], state="readonly", width=12)
            w.bind("<<ComboboxSelected>>", lambda e: self._changed())
        elif t in ("int", "float"):
            v = tk.DoubleVar() if t == "float" else tk.IntVar()
            lo, hi = spec[2], spec[3]
            if key in ("cols", "rows", "seed", "posterize", "dominant_k", "levels"):
                w = ttk.Spinbox(f, from_=lo, to=hi, textvariable=v, width=8, command=self._changed)
                w.bind("<Return>", lambda e: self._changed())
                w.bind("<FocusOut>", lambda e: self._changed())
            else:
                w = tk.Scale(f, from_=lo, to=hi, resolution=(hi - lo) / 200, orient="horizontal", variable=v,
                             showvalue=True, bg=self.C["bg1"], fg=self.C["muted"], troughcolor=self.C["bg3"],
                             highlightthickness=0, bd=0, sliderlength=12, length=150, font=("TkDefaultFont", 7),
                             command=lambda _v: self._changed())
        else:
            v = tk.StringVar()
            w = ttk.Entry(f, textvariable=v)
            w.bind("<Return>", lambda e: self._changed())
            w.bind("<FocusOut>", lambda e: self._changed())
        w.grid(row=r, column=1, sticky="ew", pady=1)
        self.vars[key] = v

    # ------------------------------------------------------------- params
    def _load_vars(self):
        self._suspend = True
        try:
            for k, v in self.vars.items():
                val = self.params.get(k)
                if isinstance(v, tk.BooleanVar):
                    v.set(bool(val))
                else:
                    v.set(val)
            self.pal_var.set(self.params.get("palette", ""))
            keys = list(MODES)
            i = keys.index(self.params["mode"])
            self.mode_list.selection_clear(0, "end")
            self.mode_list.selection_set(i)
            self.mode_list.see(i)
            self.mode_desc.configure(text=MODES[self.params["mode"]][6])
        finally:
            self._suspend = False

    def _read_vars(self) -> dict:
        p = dict(self.params)
        for k, v in self.vars.items():
            try:
                p[k] = v.get()
            except (tk.TclError, ValueError):
                pass
        pal = self.pal_var.get()
        if pal.startswith("★ "):
            for d in self.app.settings.data.get("palettes", []):
                if d["name"] == pal[2:]:
                    pal = d["chars"]
        p["palette"] = pal
        return sanitize_params(p)

    def _changed(self, push=True):
        if self._suspend:
            return
        new = self._read_vars()
        if new == self.params:
            return
        if push:
            self.undo.append(dict(self.params))
            del self.undo[:-100]
            self.redo.clear()
        self.params = new
        self.request_render()

    def _mode_selected(self):
        sel = self.mode_list.curselection()
        if not sel or self._suspend:
            return
        key = list(MODES)[sel[0]]
        self.mode_desc.configure(text=MODES[key][6])
        if key != self.params["mode"]:
            self.undo.append(dict(self.params))
            self.redo.clear()
            self.params = sanitize_params({**self.params, "mode": key})
            self.request_render()

    def _palette_chosen(self):
        self._changed()

    def _col_preset(self, v):
        if v.isdigit():
            self.vars["cols"].set(int(v))
            self._changed()

    def _spacing(self):
        try:
            self.app.exp.letter_spacing = max(0.0, min(2.0, float(self.ls_var.get())))
            self.app.exp.line_height = max(0.8, min(3.0, float(self.lh_var.get())))
        except (tk.TclError, ValueError):
            return
        self.request_render()

    def set_params(self, p: dict, push=True):
        if push:
            self.undo.append(dict(self.params))
            self.redo.clear()
        self.params = sanitize_params(p)
        self._load_vars()
        self.request_render()

    def do_undo(self):
        if self.undo:
            self.redo.append(dict(self.params))
            self.set_params(self.undo.pop(), push=False)

    def do_redo(self):
        if self.redo:
            self.undo.append(dict(self.params))
            self.set_params(self.redo.pop(), push=False)

    def reset_params(self):
        self.set_params({"mode": self.params["mode"], "cols": self.params["cols"]})

    # ------------------------------------------------------------- library
    def _add(self, name, data, img):
        self.library.append({"name": name, "data": data, "img": img})
        self.lib_list.insert("end", f"{name}  ({img.width}×{img.height})")
        self.lib_list.selection_clear(0, "end")
        self.lib_list.selection_set("end")
        self._select_image()

    def open_images(self):
        paths = filedialog.askopenfilenames(parent=self, title="Open images", filetypes=[
            ("Images", "*.png *.jpg *.jpeg *.webp *.bmp *.gif *.tif *.tiff *.ico *.svg *.avif *.heic *.heif"),
            ("All files", "*.*")])
        for path in paths:
            self.load_path(path)

    def load_path(self, path):
        try:
            with open(path, "rb") as fh:
                data = fh.read()
            img = decode_image(data, os.path.basename(path))
            self._add(os.path.basename(path), data, img)
        except (OSError, ImageDecodeError, RuntimeError) as exc:
            messagebox.showerror("Cannot open image", f"{os.path.basename(path)}:\n{exc}", parent=self)

    def paste_image(self):
        img = clipboard_image()
        if img is None:
            self.set_status("The clipboard holds no image (copy an image or image file first).")
            return
        buf = io.BytesIO()
        from PIL import Image
        Image.frombytes("RGBA", (img.width, img.height), img.to_rgba_bytes()).save(buf, "PNG")
        self._add(f"clipboard {len(self.library) + 1}", buf.getvalue(), img)

    def remove_image(self):
        if 0 <= self.current < len(self.library):
            del self.library[self.current]
            self.lib_list.delete(self.current)
            self.current = -1
            self.art = None
            if self.library:
                self.lib_list.selection_set(0)
                self._select_image()
            else:
                self.canvas.delete("all")

    def _select_image(self):
        sel = self.lib_list.curselection()
        if not sel:
            return
        self.current = sel[0]
        self._source_changed()
        self.request_render(0)

    def cur(self):
        return self.library[self.current] if 0 <= self.current < len(self.library) else None

    def _source_changed(self):
        it = self.cur()
        if not it:
            return
        from PIL import Image
        img = it["img"]
        if self.show_adjusted.get():
            img, _ = prepare(img, self.params)
        self.src_img = Image.frombytes("RGBA", (img.width, img.height), img.to_rgba_bytes())
        self.redraw()

    # ------------------------------------------------------------- rendering
    def request_render(self, delay=140):
        if self._debounce:
            self.after_cancel(self._debounce)
        self._debounce = self.after(delay, self._submit)

    def _submit(self):
        self._debounce = None
        it = self.cur()
        self.app.settings.data["image_last"] = self.params
        if not it:
            return
        p = dict(self.params)
        est = estimate_cost(it["img"].width, it["img"].height, sanitize_params(p))
        self.cost_lbl.configure(text=f"Estimate: {est['cols']}×{est['rows']} = {est['cells']:,} cells, ~{est['est_ms']:.0f} ms, "
                                     f"~{_fmt_bytes(est['est_memory_bytes'])} memory, text ≈{_fmt_bytes(est['est_text_bytes'])}")
        if est["heavy"] and not messagebox.askyesno(
                "Large render", f"This render is estimated at ~{est['est_ms'] / 1000:.1f} s and "
                                f"{_fmt_bytes(est['est_memory_bytes'])} of memory ({est['cells']:,} cells). Continue?", parent=self):
            return
        self.gen += 1
        gen, img, fx = self.gen, it["img"], (list(self.app.effects) if self.apply_fx.get() else [])
        s = self.export_settings()
        s.padding = 6
        s.scale = 1.0
        s.font_size = 12

        def job():
            art, st = render_image_art(img, p, cancel=lambda: gen != self.gen)
            if fx:
                art = apply_effects(art, fx)
            pil = render_image(art, s) if art.width * art.height <= 400_000 else None
            return art, st, pil
        self.set_status(f"Rendering {MODES[p['mode']][0]}…")
        self.worker.submit("render", gen, job)
        if self.show_adjusted.get():
            self._source_changed()

    def on_result(self, tag, gen, res, err, dt):
        if tag == "render":
            if gen != self.gen:
                return
            if err:
                if not isinstance(err, RenderCancelled):
                    self.set_status(f"Render failed: {err}")
                return
            self.art, self.stats, self.art_img = res
            st = self.stats
            est_ansi = len(to_ansi(self.art, "truecolor").encode("utf-8")) if self.art.has_color() else st["text_bytes"]
            self.info_var.set(f"Source {st['source'][0]}×{st['source'][1]}  ·  Output {st['cols']}×{st['rows']} = "
                              f"{st['chars']:,} chars  ·  ~{_fmt_bytes(est_ansi)}  ·  {dt * 1000:.0f} ms  ·  {st['label']}  ·  "
                              f"mem ~{_fmt_bytes(st['est_memory_bytes'])}")
            self.compat_lbl.configure(text="Compatibility: " + st["compat"])
            self.set_status("Ready" if self.art_img is not None else "Rendered (too large for the graphic preview — export it)")
            self.redraw()
        elif tag == "analyze":
            if err:
                self.set_status(f"Analysis failed: {err}")
            else:
                self._show_analysis(res)
        elif tag == "optimize":
            if err:
                self.set_status(f"Smart Optimize failed: {err}")
            else:
                self._show_optimize(res)
        elif tag == "batch":
            if err:
                messagebox.showerror("Batch export", str(err), parent=self)
            else:
                data, report, path = res
                atomic_write(path, data)
                ok = sum(1 for r in report if r["ok"])
                self.set_status(f"Batch: {ok}/{len(report)} images converted → {os.path.basename(path)}")
                bad = [f"{r['name']}: {r['error']}" for r in report if not r["ok"]]
                if bad:
                    messagebox.showwarning("Batch export", "Some images failed:\n" + "\n".join(bad[:12]), parent=self)

    # ------------------------------------------------------------- preview
    def _scaled(self, im, z):
        from PIL import Image
        w, h = max(1, int(im.width * z)), max(1, int(im.height * z))
        return im.resize((w, h), Image.Resampling.LANCZOS if z < 1 else Image.Resampling.NEAREST)

    def _composite(self):
        from PIL import Image
        v = self.view.get()
        art, src = self.art_img, self.src_img
        if v == "original" or art is None:
            return src
        if v == "art" or src is None:
            return art
        srcr = src.resize((max(1, int(src.width * art.height / src.height)), art.height), Image.Resampling.LANCZOS)
        if v == "side":
            out = Image.new("RGBA", (srcr.width + 12 + art.width, art.height), (5, 6, 10, 255))
            out.alpha_composite(srcr.convert("RGBA"), (0, 0))
            out.alpha_composite(art, (srcr.width + 12, 0))
            return out
        srcf = src.resize(art.size, Image.Resampling.LANCZOS).convert("RGBA")
        if v == "split":
            out = art.copy()
            out.alpha_composite(srcf.crop((0, 0, art.width, art.height // 2)), (0, 0))
            return out
        out = srcf.copy()  # slider: art on the left of the divider, original on the right
        cut = int(art.width * self.slider)
        out.alpha_composite(art.crop((0, 0, cut, art.height)), (0, 0))
        return out

    def redraw(self):
        if not hasattr(self, "canvas"):
            return
        self.canvas.delete("all")
        im = self._composite()
        if im is None:
            self.canvas.create_text(20, 20, anchor="nw", fill=self.C["muted"],
                                    text="Open or paste an image to start.\nSupported: " + ", ".join(
                                        k for k, v in decoder_capabilities()["formats"].items() if v is True))
            return
        from PIL import ImageTk
        z = self.zoom
        self.photo = ImageTk.PhotoImage(self._scaled(im, z))
        self.canvas.create_image(0, 0, anchor="nw", image=self.photo)
        self.canvas.configure(scrollregion=(0, 0, self.photo.width(), self.photo.height()))
        if self.view.get() == "slider" and self.art_img is not None:
            x = int(self.art_img.width * self.slider * z)
            self.canvas.create_line(x, 0, x, self.photo.height(), fill=self.C["accent"], width=2)
        if self.show_grid.get() and self.art is not None and self.art_img is not None and self.view.get() in ("art", "slider", "split"):
            s = self.export_settings()
            cw, ch = 12 * 0.6021 * (1 + s.letter_spacing) * z, 12 * s.line_height * z
            pad = 6 * z
            if cw >= 4:
                for x in range(self.art.width + 1):
                    self.canvas.create_line(pad + x * cw, pad, pad + x * cw, pad + self.art.height * ch, fill="#262c3a")
                for y in range(self.art.height + 1):
                    self.canvas.create_line(pad, pad + y * ch, pad + self.art.width * cw, pad + y * ch, fill="#262c3a")
        self.zoom_lbl.configure(text=f"{self.zoom * 100:.0f}%")

    def _drag_slider(self, e):
        if self.view.get() != "slider" or self.art_img is None:
            return
        x = self.canvas.canvasx(e.x) / max(1e-6, self.zoom)
        self.slider = max(0.0, min(1.0, x / self.art_img.width))
        self.redraw()

    def set_zoom(self, z):
        self.zoom = max(0.05, min(8.0, z))
        self.redraw()

    def fit(self):
        im = self._composite()
        if im is None:
            return
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        self.set_zoom(min(w / im.width, h / im.height) * 0.98)

    def fullscreen(self):
        im = self._composite()
        if im is None:
            return
        from PIL import ImageTk
        top = tk.Toplevel(self)
        top.attributes("-fullscreen", True)
        top.configure(bg="#000")
        sw, sh = top.winfo_screenwidth(), top.winfo_screenheight()
        z = min(sw / im.width, sh / im.height)
        ph = ImageTk.PhotoImage(self._scaled(im, z))
        lbl = tk.Label(top, image=ph, bg="#000")
        lbl.image = ph
        lbl.pack(expand=True)
        top.bind("<Escape>", lambda e: top.destroy())
        top.bind("<Button-1>", lambda e: top.destroy())

    # ------------------------------------------------------------- analysis / optimise
    def run_analyze(self):
        it = self.cur()
        if it:
            self.set_status("Analyzing…")
            self.worker.submit("analyze", 0, lambda: analyze(it["img"]))

    def _show_analysis(self, a):
        top = tk.Toplevel(self)
        top.title("Image analysis")
        top.configure(bg=self.C["bg1"])
        txt = tk.Text(top, width=78, height=22, bg=self.C["bg2"], fg=self.C["text"], borderwidth=0)
        txt.pack(fill="both", expand=True, padx=10, pady=10)
        m = a["metrics"]
        lines = [f"{k}: {v}" for k, v in m.items() if k not in ("histogram16", "local_luminance_4x4", "dominant_colors")]
        lines.append("dominant colours: " + ", ".join(f"{d['color']} ({d['share'] * 100:.0f}%)" for d in m["dominant_colors"]))
        lines.append("")
        lines.append("RECOMMENDATIONS (rule-based, deterministic — every value can be overridden):")
        for r in a["recommendations"]:
            lines.append(f"  {r['key']} = {r['value']}    ← {r['reason']}")
        txt.insert("1.0", "\n".join(lines))
        txt.configure(state="disabled")

        def apply():
            self.set_params(recommended_params(a, self.params))
            top.destroy()
        ttk.Button(top, text="Apply recommendations", style="Accent.TButton", command=apply).pack(pady=(0, 10))
        self.set_status("Analysis complete")

    def run_optimize(self):
        it = self.cur()
        if not it:
            return
        preset = self.opt_var.get()
        self.set_status(f"Smart Optimize ({OPT_PRESETS[preset]['label']}): rendering candidates…")
        base = dict(self.params)
        self.worker.submit("optimize", 0, lambda: optimize(it["img"], base, preset))

    def _show_optimize(self, res):
        top = tk.Toplevel(self)
        top.title(f"Smart Optimize — {res['label']}")
        top.configure(bg=self.C["bg1"])
        ttk.Label(top, text=res["note"], wraplength=640, style="Muted.TLabel").pack(padx=10, pady=(10, 4), anchor="w")
        tree = ttk.Treeview(top, columns=("score", "mode", "ssim", "edge", "de", "bytes"), show="headings", height=8)
        for c, w in (("score", 70), ("mode", 170), ("ssim", 70), ("edge", 70), ("de", 70), ("bytes", 90)):
            tree.heading(c, text={"de": "ΔE", "edge": "edge corr"}.get(c, c))
            tree.column(c, width=w)
        for i, r in enumerate(res["results"]):
            q = r["metrics"]
            tree.insert("", "end", iid=str(i), values=(r["score"], MODES[r["params"]["mode"]][0], q["ssim"], q["edge_corr"],
                                                         q["color_de"], q["bytes"]))
        tree.pack(fill="both", expand=True, padx=10)

        def apply():
            sel = tree.selection()
            if sel:
                self.set_params(res["results"][int(sel[0])]["params"])
                top.destroy()
        ttk.Button(top, text="Use selected (adjust afterwards as you like)", style="Accent.TButton", command=apply).pack(pady=10)
        self.set_status(f"Smart Optimize evaluated {res['evaluated']} candidates in {res['ms']} ms")

    # ------------------------------------------------------------- palettes & presets
    def sort_palette(self):
        p = self.pal_var.get()
        if p and p not in PALETTES and not p.startswith("★ "):
            self.pal_var.set("".join(sort_by_density(list(p))))
            self._changed()

    def save_palette(self):
        p = self.params["palette"]
        if not p:
            return
        name = simpledialog.askstring("Save palette", "Name:", parent=self)
        if name:
            chars = PALETTES[p]["chars"] if p in PALETTES else p
            lst = [d for d in self.app.settings.data["palettes"] if d["name"] != name]
            lst.append({"name": name[:80], "chars": chars})
            self.app.settings.data["palettes"] = lst
            self.app.settings.save()
            self.pal_combo.configure(values=[""] + list(PALETTES) + [f"★ {d['name']}" for d in lst])

    def palette_from_font(self):
        try:
            font = self.app.fonts.font(self.app.current_fid)
            pal = palette_from_figlet(font)
        except Exception as exc:  # noqa: BLE001
            self.set_status(f"Cannot build a palette from this font: {exc}")
            return
        self.pal_var.set(pal)
        self._changed()
        self.set_status(f"Palette from {self.app.fonts.entries[self.app.current_fid].name}: {pal!r}")

    def import_palette(self):
        path = filedialog.askopenfilename(parent=self, filetypes=[("Palette JSON", "*.json")])
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as fh:
                items = import_palettes(fh.read(2_000_000))
        except (OSError, ValueError) as exc:
            messagebox.showerror("Import palettes", str(exc), parent=self)
            return
        lst = self.app.settings.data["palettes"]
        names = {d["name"] for d in lst}
        lst.extend(d for d in items if d["name"] not in names)
        self.app.settings.save()
        self.pal_combo.configure(values=[""] + list(PALETTES) + [f"★ {d['name']}" for d in lst])
        self.set_status(f"Imported {len(items)} palettes")

    def export_palette(self):
        lst = self.app.settings.data["palettes"] or [{"name": "current", "chars": self.params["palette"] or " .:-=+*#%@"}]
        self.ask_save("Export palettes", ".json", export_palettes(lst).encode("utf-8"))

    def save_preset(self):
        name = simpledialog.askstring("Save preset", "Preset name:", parent=self)
        if name:
            self.app.settings.data["image_presets"][name[:80]] = self.params
            self.app.settings.save()
            self.preset_combo.configure(values=sorted(self.app.settings.data["image_presets"]))

    def load_preset(self):
        p = self.app.settings.data["image_presets"].get(self.preset_var.get())
        if p:
            self.set_params(p)

    def delete_preset(self):
        if self.app.settings.data["image_presets"].pop(self.preset_var.get(), None) is not None:
            self.app.settings.save()
            self.preset_combo.configure(values=sorted(self.app.settings.data["image_presets"]))
            self.preset_var.set("")

    # ------------------------------------------------------------- export
    def export_art(self):
        if self.art is None:
            return
        fmt = self.fmt.get()
        try:
            data = export_bytes(self.art, fmt, self.export_settings())
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Export", str(exc), parent=self)
            return
        self.ask_save("Export text art", FORMATS[fmt][1], data)

    def copy(self, kind):
        if self.art is None:
            return
        s = to_txt(self.art) if kind == "text" else to_ansi(self.art, self.export_settings().ansi_mode)
        self.clipboard_clear()
        self.clipboard_append(s)
        self.set_status(f"Copied {len(s):,} characters ({kind})")

    def export_comparison(self):
        it = self.cur()
        if it and self.art is not None:
            self.ask_save("Comparison PNG", ".png", comparison_png(it["img"], self.art, self.export_settings()))

    def export_typo(self, fmt):
        it = self.cur()
        if not it:
            return
        comp = compose_typographic(it["img"], self.params, self.typo_size.get(), self.typo_vary.get(), self.typo_rot.get())
        data = composition_png(comp) if fmt == "png" else composition_svg(comp).encode("utf-8")
        self.ask_save("Typographic composition (graphic)", "." + fmt, data)

    def batch_export(self):
        if not self.library:
            self.set_status("The queue is empty — open several images first.")
            return
        path = filedialog.asksaveasfilename(parent=self, title=f"Batch export as ZIP ({self.fmt.get()})",
                                            defaultextension=".zip", filetypes=[("ZIP", "*.zip")])
        if not path:
            return
        items = [(it["name"], it["data"]) for it in self.library]
        p, fmt, s = dict(self.params), self.fmt.get(), self.export_settings()
        self.set_status(f"Batch converting {len(items)} images…")
        self.worker.submit("batch", 0, lambda: (*batch_convert(items, p, fmt, s), path))

    def save_project(self):
        it = self.cur()
        data = make_image_project(self.params, it["data"] if it else None, it["name"] if it else "",
                                  self.app.effects if self.apply_fx.get() else [], {})
        self.ask_save("Save image project", ".leerbox-image.json", data.encode("utf-8"))

    def open_project(self, path=None):
        path = path or filedialog.askopenfilename(parent=self, filetypes=[("LeerBox image project", "*.json")])
        if not path:
            return
        try:
            with open(path, "rb") as fh:
                d = parse_image_project(fh.read())
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Open project", str(exc), parent=self)
            return
        if d["image"]:
            try:
                self._add(d["image_name"] or "project image", d["image"], decode_image(d["image"], d["image_name"]))
            except ImageDecodeError as exc:
                messagebox.showwarning("Open project", f"Embedded image could not be decoded: {exc}", parent=self)
        if d["effects"]:
            self.app.effects = d["effects"]
            self.apply_fx.set(True)
        self.set_params(d["params"])


# ======================================================================= Animation Studio
class AnimationWorkspace(_Base):
    def __init__(self, parent, app, colors, image_ws: ImageWorkspace):
        super().__init__(parent, app, colors)
        self.image_ws = image_ws
        self.frames, self.durations, self.info = [], [], {}
        self.arts, self.art_durs, self.photos = [], [], []
        self.pos = 0
        self.playing = False
        self._timer = None
        self.mode = tk.StringVar(value="braille")
        self.cols = tk.IntVar(value=80)
        self.start, self.end, self.step = tk.IntVar(value=0), tk.IntVar(value=-1), tk.IntVar(value=1)
        self.fps = tk.DoubleVar(value=0.0)
        self.loop = tk.BooleanVar(value=True)
        self._build()

    def _build(self):
        paned = ttk.Panedwindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True)
        left = ttk.Frame(paned, padding=(10, 8))
        center = ttk.Frame(paned, style="Bg0.TFrame", padding=(8, 8))
        right = ttk.Frame(paned, padding=(10, 8))
        paned.add(left, weight=0)
        paned.add(center, weight=1)
        paned.add(right, weight=0)
        self._paned = paned
        self._head(left, "ANIMATION SOURCE")
        ttk.Button(left, text="Open GIF / animated WebP / APNG…", command=self.open_anim).pack(fill="x")
        ttk.Label(left, text="Video files: no local video decoder is available in the Python edition. The HTML "
                             "edition converts video using the browser's own decoder.", style="Muted.TLabel",
                  wraplength=240).pack(anchor="w", pady=4)
        self._head(left, "FRAMES")
        self.frame_list = tk.Listbox(left, height=18, bg=self.C["bg2"], fg=self.C["text"], selectbackground=self.C["sel"],
                                     highlightthickness=0, borderwidth=0, exportselection=False)
        self.frame_list.pack(fill="both", expand=True)
        self.frame_list.bind("<<ListboxSelect>>", lambda e: self._show_frame_sel())
        tb = ttk.Frame(center, style="Bg0.TFrame")
        tb.pack(fill="x")
        self.play_btn = ttk.Button(tb, text="▶ Play", command=self.toggle_play)
        self.play_btn.pack(side="left")
        ttk.Checkbutton(tb, text="Loop", variable=self.loop, style="Bar.TCheckbutton").pack(side="left", padx=6)
        self.scrub = ttk.Scale(tb, from_=0, to=0, orient="horizontal", command=lambda v: self.show(int(float(v))))
        self.scrub.pack(side="left", fill="x", expand=True, padx=8)
        self.frame_lbl = ttk.Label(tb, text="", style="Bar.TLabel")
        self.frame_lbl.pack(side="right")
        self.canvas = tk.Canvas(center, bg="#05060a", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, pady=(6, 0))
        self._head(right, "CONVERSION")
        f = ttk.Frame(right); f.pack(fill="x"); f.columnconfigure(1, weight=1)
        rows = [("Mode", ttk.Combobox(f, textvariable=self.mode, values=list(MODES), state="readonly", width=14)),
                ("Width (chars)", ttk.Spinbox(f, from_=8, to=400, textvariable=self.cols, width=8)),
                ("First frame", ttk.Spinbox(f, from_=0, to=9999, textvariable=self.start, width=8)),
                ("Last frame (−1 = end)", ttk.Spinbox(f, from_=-1, to=9999, textvariable=self.end, width=8)),
                ("Use every Nth frame", ttk.Spinbox(f, from_=1, to=100, textvariable=self.step, width=8)),
                ("Frame rate (0 = original)", ttk.Spinbox(f, from_=0, to=60, increment=1, textvariable=self.fps, width=8))]
        for r, (lbl, w) in enumerate(rows):
            ttk.Label(f, text=lbl, style="Muted.TLabel").grid(row=r, column=0, sticky="w", pady=2, padx=(0, 6))
            w.grid(row=r, column=1, sticky="ew", pady=2)
        ttk.Label(right, text="All other settings (palette, adjustments, colours, dithering …) are taken from the "
                              "Image Studio.", style="Muted.TLabel", wraplength=260).pack(anchor="w", pady=4)
        ttk.Button(right, text="Convert frames", style="Accent.TButton", command=self.convert).pack(fill="x")
        self._head(right, "EXPORT ANIMATION")
        for label, kind in (("Animated HTML…", "html"), ("GIF…", "gif"), ("Frame sequence (TXT ZIP)…", "zip_txt"),
                            ("Frame sequence (PNG ZIP)…", "zip_png"), ("ANSI script (Bash)…", "sh"),
                            ("ANSI script (PowerShell)…", "ps1")):
            ttk.Button(right, text=label, command=lambda k=kind: self.export(k)).pack(fill="x", pady=1)
        ttk.Label(right, text="WebM/MP4: not available here — no local video encoder is bundled with the Python "
                              "edition (the HTML edition records WebM where the browser supports it).",
                  style="Muted.TLabel", wraplength=260).pack(anchor="w", pady=(6, 0))
        bar = ttk.Frame(self, style="Bg0.TFrame", padding=(14, 3))
        bar.pack(fill="x")
        self.status_var = tk.StringVar(value="Open an animated image to start.")
        ttk.Label(bar, textvariable=self.status_var, style="Bar.TLabel").pack(side="left")

    def open_anim(self, path=None):
        path = path or filedialog.askopenfilename(parent=self, filetypes=[("Animations", "*.gif *.webp *.png *.apng"),
                                                                           ("All files", "*.*")])
        if not path:
            return
        try:
            with open(path, "rb") as fh:
                self.frames, self.durations, self.info = decode_frames(fh.read())
        except (OSError, ImageDecodeError, RuntimeError) as exc:
            messagebox.showerror("Open animation", str(exc), parent=self)
            return
        self.frame_list.delete(0, "end")
        for i, d in enumerate(self.durations):
            self.frame_list.insert("end", f"frame {i + 1:4d}   {d} ms")
        self.arts = []
        self.set_status(f"{os.path.basename(path)}: {len(self.frames)} frames, {self.info['source_size'][0]}×"
                        f"{self.info['source_size'][1]}, loop={self.info.get('loop', 0)}")
        self.mode.set(self.image_ws.params["mode"])
        self.cols.set(min(200, self.image_ws.params["cols"]))

    def convert(self):
        if not self.frames:
            return
        self.stop()
        p = dict(self.image_ws.params)
        try:
            p.update(mode=self.mode.get(), cols=int(self.cols.get()))
            st, en, sp, fps = int(self.start.get()), int(self.end.get()), int(self.step.get()), float(self.fps.get())
        except (tk.TclError, ValueError):
            return
        frames, durs = self.frames, self.durations
        s = self.export_settings()
        s.padding, s.font_size, s.scale = 6, 10, 1.0
        self.gen += 1
        self.set_status("Converting frames…")

        def job():
            arts, d2, stats = convert_animation(frames, durs, p, st, en, sp, fps)
            pils = [render_image(a, s) for a in arts] if arts and arts[0].width * arts[0].height * len(arts) < 3_000_000 else []
            return arts, d2, stats, pils
        self.worker.submit("convert", self.gen, job)

    def on_result(self, tag, gen, res, err, dt):
        if tag == "convert" and gen == self.gen:
            if err:
                self.set_status(f"Conversion failed: {err}")
                return
            from PIL import ImageTk
            self.arts, self.art_durs, stats, pils = res
            self.photos = [ImageTk.PhotoImage(im) for im in pils]
            self.scrub.configure(to=max(0, len(self.arts) - 1))
            self.set_status(f"Converted {stats['frames']} frames in {stats['ms']} ms ({MODES[stats['mode']][0]})"
                            + ("" if self.photos else " — too large for preview playback; export it"))
            self.show(0)
        elif tag == "export":
            if err:
                messagebox.showerror("Export animation", str(err), parent=self)
            else:
                path, data = res
                atomic_write(path, data)
                self.set_status(f"Saved {os.path.basename(path)} ({_fmt_bytes(len(data))})")

    def show(self, i):
        if not self.arts:
            if self.frames and 0 <= i < len(self.frames):
                from PIL import Image, ImageTk
                f = self.frames[i]
                self._raw = ImageTk.PhotoImage(Image.frombytes("RGBA", (f.width, f.height), f.to_rgba_bytes()))
                self.canvas.delete("all")
                self.canvas.create_image(0, 0, anchor="nw", image=self._raw)
            return
        self.pos = max(0, min(len(self.arts) - 1, i))
        self.canvas.delete("all")
        if self.photos:
            self.canvas.create_image(0, 0, anchor="nw", image=self.photos[self.pos])
        self.frame_lbl.configure(text=f"{self.pos + 1}/{len(self.arts)}  ·  {self.art_durs[self.pos]} ms")

    def _show_frame_sel(self):
        sel = self.frame_list.curselection()
        if sel:
            self.show(sel[0] if not self.arts else min(sel[0], len(self.arts) - 1))

    def toggle_play(self):
        if self.playing:
            self.stop()
        elif self.arts and self.photos:
            self.playing = True
            self.play_btn.configure(text="⏸ Pause")
            self._tick()

    def stop(self):
        self.playing = False
        self.play_btn.configure(text="▶ Play")
        if self._timer:
            self.after_cancel(self._timer)
            self._timer = None

    def _tick(self):
        if not self.playing:
            return
        self.show(self.pos)
        self.scrub.set(self.pos)
        d = self.art_durs[self.pos]
        nxt = self.pos + 1
        if nxt >= len(self.arts):
            if not self.loop.get():
                self.stop()
                return
            nxt = 0
        self.pos = nxt
        self._timer = self.after(max(15, d), self._tick)

    def export(self, kind):
        if not self.arts:
            self.set_status("Convert the frames first.")
            return
        ext = {"html": ".html", "gif": ".gif", "zip_txt": ".zip", "zip_png": ".zip", "sh": ".sh", "ps1": ".ps1"}[kind]
        path = filedialog.asksaveasfilename(parent=self, defaultextension=ext, filetypes=[(ext, "*" + ext)])
        if not path:
            return
        arts, durs, loop, s = self.arts, self.art_durs, self.loop.get(), self.export_settings()

        def job():
            if kind == "html":
                return path, to_animated_html(arts, durs, s, loop).encode("utf-8")
            if kind == "gif":
                return path, to_gif(arts, durs, s, loop)
            if kind.startswith("zip"):
                return path, to_frame_zip(arts, kind[4:], s, durs)
            shell = "bash" if kind == "sh" else "powershell"
            text = to_ansi_script(arts, durs, shell, s.ansi_mode if s.ansi_mode != "none" else "truecolor", loop)
            return path, (("﻿" if kind == "ps1" else "") + text).encode("utf-8")
        self.set_status("Exporting…")
        self.worker.submit("export", self.gen, job)

