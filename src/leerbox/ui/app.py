"""ApplicationUI — LeerBox Text Art Studio 3.0 Ultimate Edition (Tkinter desktop edition)."""
from __future__ import annotations

import copy
import json
import logging
import os
import queue
import random
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import colorchooser, filedialog, messagebox, ttk

from ..arabic import contains_arabic, visual_text
from ..art import Art, hex_to_rgb, rgb_to_hex
from ..effects import DEFAULTS as FX_DEFAULTS, EFFECT_INFO, FRAMES, new_effect, pipeline_representation
from ..export import CODE_LANGS, FORMATS, HAVE_PILLOW, ExportSettings, export_bytes, to_ansi, to_code, to_html_fragment, to_markdown, to_txt
from ..fontdb import FontManager
from ..imageart import RAMPS, ImageData, ImageOptions, image_to_art, load_image
from ..project import SettingsManager, atomic_write, make_project, parse_project
from ..smart import curated_designs, preview_scale, random_design, recommend, width_warning
from ..textart import RenderingEngine, TextOptions
from ..unicode_styles import BOX_STYLES, ENCODINGS, STYLE_NAMES, decode, encode, stylize, text_box
from .image_ws import AnimationWorkspace, ImageWorkspace

try:  # graphic preview needs Pillow's Tk bridge
    from PIL import ImageTk as _ImageTk  # noqa: F401
    HAVE_IMAGETK = True
except Exception:  # noqa: BLE001
    HAVE_IMAGETK = False

APP_NAME = "LeerBox Text Art Studio"
APP_VERSION = "3.0"
APP_EDITION = "Ultimate Edition"

LOG = logging.getLogger("leerbox")

C = {
    "bg0": "#0b0d12", "bg1": "#11141b", "bg2": "#171b24", "bg3": "#1f2430", "line": "#272d3a",
    "text": "#e6e9ef", "muted": "#8a93a6", "dim": "#5d6578", "accent": "#7c8cff", "accent2": "#a78bfa",
    "ok": "#4ade80", "warn": "#fbbf24", "err": "#f87171", "sel": "#2b3350",
}

FX_CHOICES = {
    "mode": ["horizontal", "vertical", "diagonal", "diagonal_up", "radial"],
    "target": ["fg", "bg"], "direction": ["se", "sw", "ne", "nw", "s", "e", "n", "w"],
    "style": list(FRAMES), "angle": [90, 180, 270],
}
COLOR_KEYS = {"fg", "bg", "color", "color1", "color2"}


def _mono_family(root) -> str:
    fams = set(tkfont.families(root))
    for f in ("Cascadia Mono", "Cascadia Code", "Consolas", "DejaVu Sans Mono", "Menlo", "Courier New"):
        if f in fams:
            return f
    return "TkFixedFont"


def _ui_family(root) -> str:
    fams = set(tkfont.families(root))
    for f in ("Segoe UI Variable Text", "Segoe UI", "Inter", "Helvetica"):
        if f in fams:
            return f
    return "TkDefaultFont"


# ---------------------------------------------------------------------------
# Windows clipboard (CF_HTML) helper
# ---------------------------------------------------------------------------

def copy_html_windows(fragment: str, plain: str) -> bool:
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes
        user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
        user32.OpenClipboard.argtypes = [wintypes.HWND]
        kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
        kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
        user32.SetClipboardData.restype = wintypes.HANDLE
        cf_html = user32.RegisterClipboardFormatW("HTML Format")
        head = "Version:0.9\r\nStartHTML:{0:010d}\r\nEndHTML:{1:010d}\r\nStartFragment:{2:010d}\r\nEndFragment:{3:010d}\r\n"
        pre = "<html><body><!--StartFragment-->"
        post = "<!--EndFragment--></body></html>"
        dummy = head.format(0, 0, 0, 0)
        start_html = len(dummy.encode("utf-8"))
        start_frag = start_html + len(pre.encode("utf-8"))
        end_frag = start_frag + len(fragment.encode("utf-8"))
        end_html = end_frag + len(post.encode("utf-8"))
        payload = (head.format(start_html, end_html, start_frag, end_frag) + pre + fragment + post).encode("utf-8") + b"\0"
        text_payload = (plain.replace("\n", "\r\n") + "\0").encode("utf-16-le")
        if not user32.OpenClipboard(None):
            return False
        try:
            user32.EmptyClipboard()
            for fmt, data in ((cf_html, payload), (13, text_payload)):  # 13 = CF_UNICODETEXT
                h = kernel32.GlobalAlloc(0x0002, len(data))
                p = kernel32.GlobalLock(h)
                ctypes.memmove(p, data, len(data))
                kernel32.GlobalUnlock(h)
                user32.SetClipboardData(fmt, h)
        finally:
            user32.CloseClipboard()
        return True
    except Exception as exc:  # noqa: BLE001
        LOG.warning("HTML clipboard failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Background workers
# ---------------------------------------------------------------------------

class LatestJobWorker(threading.Thread):
    """Runs only the most recent job; older pending jobs are discarded (cancellation)."""

    def __init__(self, results: queue.Queue):
        super().__init__(daemon=True)
        self.results = results
        self.cv = threading.Condition()
        self.job = None

    def submit(self, job) -> None:
        with self.cv:
            self.job = job
            self.cv.notify()

    def run(self) -> None:
        while True:
            with self.cv:
                while self.job is None:
                    self.cv.wait()
                job, self.job = self.job, None
            tag, gen, fn = job
            t0 = time.perf_counter()
            try:
                res, err = fn(), None
            except Exception as exc:  # noqa: BLE001 - reported to the UI
                LOG.exception("render job failed")
                res, err = None, exc
            self.results.put((tag, gen, res, err, time.perf_counter() - t0))


class GalleryWorker(threading.Thread):
    def __init__(self, results: queue.Queue):
        super().__init__(daemon=True)
        self.results = results
        self.q: queue.Queue = queue.Queue()
        self.gen = 0

    def run(self) -> None:
        while True:
            gen, key, fn = self.q.get()
            if gen != self.gen:
                continue  # outdated request
            try:
                res, err = fn(), None
            except Exception as exc:  # noqa: BLE001
                res, err = None, exc
            self.results.put(("gallery", gen, (key, res), err, 0))


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

class StudioApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.settings = SettingsManager()
        self.fonts = FontManager(user_dir=self.settings.dir)
        self.engine = RenderingEngine(self.fonts)
        self.opts = TextOptions()
        self.effects: list[dict] = []
        self.exp = ExportSettings()
        self.current_fid = "fig:standard"
        self.mode = "text"
        self.view = "preview"
        self.current_art: Art | None = None
        self.image_data: ImageData | None = None
        self.filtered: list[str] = []
        self.compare: list[str] = []
        self.render_gen = 0
        self.results: queue.Queue = queue.Queue()
        self.worker = LatestJobWorker(self.results)
        self.worker.start()
        self.gworker = GalleryWorker(self.results)
        self.gworker.start()
        self.gallery_cache: dict[str, Art | Exception] = {}
        self.gallery_items: dict[str, int] = {}
        self.zoom = float(self.settings.data.get("zoom", 1.0) or 1.0)
        self._debounce = None
        self._search_debounce = None
        self._color_tags: dict[int, str] = {}
        self._fx_widgets: list = []
        self.mono = _mono_family(root)
        self.ui = _ui_family(root)
        self.preview_font = tkfont.Font(family=self.mono, size=self._zoom_size())
        self.gallery_font = tkfont.Font(family=self.mono, size=6)
        self._setup_window()
        self._setup_style()
        self._build()
        self._restore_state()
        self.refresh_fonts()
        self.root.after(40, self._poll)
        if self.settings.error:
            self.status(self.settings.error, "warn")

    # ------------------------------------------------------------- window
    def _setup_window(self) -> None:
        r = self.root
        r.title(f"{APP_NAME} {APP_VERSION} — {APP_EDITION}")
        r.configure(bg=C["bg0"])
        r.minsize(980, 620)
        geo = self.settings.data.get("geometry")
        r.geometry(geo if geo else "1480x900")
        r.protocol("WM_DELETE_WINDOW", self.on_close)
        r.bind("<Control-s>", lambda e: self.save_project())
        r.bind("<Control-o>", lambda e: self.open_project())
        r.bind("<Control-e>", lambda e: self.export_dialog())
        r.bind("<Control-Shift-C>", lambda e: self.copy_text())
        r.bind("<F11>", lambda e: self.fullscreen())
        r.bind("<Control-plus>", lambda e: self.set_zoom(self.zoom * 1.15))
        r.bind("<Control-equal>", lambda e: self.set_zoom(self.zoom * 1.15))
        r.bind("<Control-minus>", lambda e: self.set_zoom(self.zoom / 1.15))
        r.bind("<Control-0>", lambda e: self.set_zoom(1.0))
        r.bind("<Control-r>", lambda e: self.random_font())
        r.bind("<Control-v>", self._paste_image_shortcut, add="+")

    def _setup_style(self) -> None:
        s = ttk.Style(self.root)
        s.theme_use("clam")
        f = (self.ui, 10)
        self.root.option_add("*Font", f)
        self.root.option_add("*TCombobox*Listbox.background", C["bg2"])
        self.root.option_add("*TCombobox*Listbox.foreground", C["text"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", C["sel"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", C["text"])
        self.root.option_add("*TCombobox*Listbox.font", f)
        self.root.option_add("*Menu.background", C["bg2"])
        self.root.option_add("*Menu.foreground", C["text"])
        self.root.option_add("*Menu.activeBackground", C["sel"])
        self.root.option_add("*Menu.activeForeground", C["text"])
        s.configure(".", background=C["bg1"], foreground=C["text"], fieldbackground=C["bg2"], bordercolor=C["line"],
                    lightcolor=C["bg2"], darkcolor=C["bg2"], troughcolor=C["bg1"], focuscolor=C["accent"],
                    selectbackground=C["sel"], selectforeground=C["text"], insertcolor=C["text"], font=f)
        s.configure("TFrame", background=C["bg1"])
        s.configure("Bg0.TFrame", background=C["bg0"])
        s.configure("Card.TFrame", background=C["bg2"])
        s.configure("TLabel", background=C["bg1"], foreground=C["text"])
        s.configure("Muted.TLabel", foreground=C["muted"])
        s.configure("Head.TLabel", foreground=C["muted"], font=(self.ui, 8, "bold"))
        s.configure("Brand.TLabel", background=C["bg0"], foreground=C["text"], font=(self.ui, 13, "bold"))
        s.configure("Sub.TLabel", background=C["bg0"], foreground=C["muted"], font=(self.ui, 9))
        s.configure("Bar.TLabel", background=C["bg0"], foreground=C["muted"], font=(self.ui, 9))
        s.configure("TButton", background=C["bg3"], foreground=C["text"], borderwidth=0, padding=(10, 5),
                    focusthickness=0, relief="flat")
        s.map("TButton", background=[("pressed", C["sel"]), ("active", "#29303f")])
        s.configure("Accent.TButton", background=C["accent"], foreground="#0b0d12", font=(self.ui, 10, "bold"))
        s.map("Accent.TButton", background=[("pressed", "#6676f0"), ("active", "#8f9cff")])
        s.configure("Tool.TButton", padding=(6, 3), background=C["bg2"])
        s.configure("Tab.TButton", padding=(14, 6), background=C["bg0"], foreground=C["muted"])
        s.map("Tab.TButton", background=[("active", C["bg2"])], foreground=[("active", C["text"])])
        s.configure("TabOn.TButton", padding=(14, 6), background=C["bg2"], foreground=C["text"], font=(self.ui, 10, "bold"))
        s.configure("ScopeOn.TButton", padding=(6, 3), background=C["sel"], foreground=C["text"], font=(self.ui, 10, "bold"))
        s.configure("TEntry", fieldbackground=C["bg2"], foreground=C["text"], bordercolor=C["line"], padding=4)
        s.map("TEntry", bordercolor=[("focus", C["accent"])])
        s.configure("TSpinbox", fieldbackground=C["bg2"], foreground=C["text"], arrowcolor=C["muted"], padding=3,
                    background=C["bg3"])
        s.configure("TCombobox", fieldbackground=C["bg2"], foreground=C["text"], arrowcolor=C["muted"], padding=3,
                    background=C["bg3"])
        s.map("TCombobox", fieldbackground=[("readonly", C["bg2"])], foreground=[("readonly", C["text"])],
              selectbackground=[("readonly", C["bg2"])])
        s.configure("TCheckbutton", background=C["bg1"], foreground=C["text"], indicatorbackground=C["bg2"],
                    indicatorforeground=C["accent"])
        s.map("TCheckbutton", background=[("active", C["bg1"])], indicatorbackground=[("selected", C["accent"])])
        s.configure("TNotebook", background=C["bg1"], borderwidth=0, tabmargins=(0, 0, 0, 0))
        s.configure("TNotebook.Tab", background=C["bg1"], foreground=C["muted"], padding=(12, 6), borderwidth=0)
        s.map("TNotebook.Tab", background=[("selected", C["bg2"])], foreground=[("selected", C["text"])])
        s.configure("Treeview", background=C["bg2"], fieldbackground=C["bg2"], foreground=C["text"], rowheight=24,
                    borderwidth=0)
        s.configure("Treeview.Heading", background=C["bg3"], foreground=C["muted"], borderwidth=0)
        s.map("Treeview", background=[("selected", C["sel"])])
        for o in ("Vertical", "Horizontal"):
            s.configure(f"{o}.TScrollbar", background=C["bg3"], troughcolor=C["bg1"], bordercolor=C["bg1"],
                        arrowcolor=C["muted"], gripcount=0, relief="flat")
        s.configure("TLabelframe", background=C["bg1"], bordercolor=C["line"])
        s.configure("TLabelframe.Label", background=C["bg1"], foreground=C["muted"], font=(self.ui, 8, "bold"))
        s.configure("TScale", background=C["bg1"], troughcolor=C["bg3"])
        s.configure("TPanedwindow", background=C["bg0"])
        s.configure("Bar.TCheckbutton", background=C["bg0"], foreground=C["muted"], indicatorbackground=C["bg2"])
        s.map("Bar.TCheckbutton", background=[("active", C["bg0"])], indicatorbackground=[("selected", C["accent"])])

    # --------------------------------------------------------------- layout
    def _build(self) -> None:
        r = self.root
        top = ttk.Frame(r, style="Bg0.TFrame", padding=(14, 8))
        top.pack(fill="x")
        logo = tk.Canvas(top, width=28, height=28, bg=C["bg0"], highlightthickness=0)
        logo.create_rectangle(2, 2, 26, 26, outline=C["accent"], width=2)
        logo.create_text(14, 14, text="LB", fill=C["accent"], font=(self.ui, 9, "bold"))
        logo.pack(side="left", padx=(0, 10))
        b = ttk.Frame(top, style="Bg0.TFrame")
        b.pack(side="left")
        ttk.Label(b, text="LeerBox  Text Art Studio", style="Brand.TLabel").pack(anchor="w")
        ttk.Label(b, text=f"{APP_VERSION} {APP_EDITION}  ·  offline  ·  {self.fonts.stats()['genuine']} genuine FIGlet/TOIlet fonts",
                  style="Sub.TLabel").pack(anchor="w")
        tabs = ttk.Frame(top, style="Bg0.TFrame")
        tabs.pack(side="left", padx=30)
        self.mode_buttons = {}
        for key, label in (("text", "Text Art"), ("unicode", "Unicode Styles"), ("encode", "Encoders"),
                           ("boxes", "Boxes & Banners"), ("image", "Image Studio"), ("animation", "Animation Studio")):
            bt = ttk.Button(tabs, text=label, style="Tab.TButton", command=lambda k=key: self.set_mode(k))
            bt.pack(side="left", padx=1)
            self.mode_buttons[key] = bt
        right = ttk.Frame(top, style="Bg0.TFrame")
        right.pack(side="right")
        for label, cmd in (("About", self.about), ("Save project", self.save_project), ("Open project", self.open_project)):
            ttk.Button(right, text=label, style="Tool.TButton", command=cmd).pack(side="right", padx=2)

        self.paned = ttk.Panedwindow(r, orient="horizontal")
        self.paned.pack(fill="both", expand=True)
        self.left = ttk.Frame(self.paned, padding=(10, 8))
        self.center = ttk.Frame(self.paned, style="Bg0.TFrame", padding=(8, 8))
        self.rightp = ttk.Frame(self.paned, padding=(8, 8))
        self.paned.add(self.left, weight=0)
        self.paned.add(self.center, weight=1)
        self.paned.add(self.rightp, weight=0)
        self._build_left()
        self._build_center()
        self._build_right()

        bar = ttk.Frame(r, style="Bg0.TFrame", padding=(14, 4))
        bar.pack(fill="x")
        self.bar = bar
        self.workspaces: dict[str, ttk.Frame] = {}
        self.status_var = tk.StringVar(value="Ready")
        self.status_lbl = ttk.Label(bar, textvariable=self.status_var, style="Bar.TLabel")
        self.status_lbl.pack(side="left")
        self.size_var = tk.StringVar()
        ttk.Label(bar, textvariable=self.size_var, style="Bar.TLabel").pack(side="right")
        self.root.after(100, lambda: self._set_sash())

    def _set_sash(self) -> None:
        try:
            w = self.root.winfo_width()
            self.paned.sashpos(0, 290)
            self.paned.sashpos(1, max(700, w - 360))
        except tk.TclError:
            pass

    # ---------------------------------------------------------- left panel
    def _build_left(self) -> None:
        p = self.left
        ttk.Label(p, text="FONT LIBRARY", style="Head.TLabel").pack(anchor="w")
        self.search_var = tk.StringVar()
        e = ttk.Entry(p, textvariable=self.search_var)
        e.pack(fill="x", pady=(6, 4))
        e.insert(0, "")
        self.search_var.trace_add("write", lambda *a: self._debounced_refresh())
        self.scope_var = tk.StringVar(value="All")
        sc = ttk.Frame(p)
        sc.pack(fill="x", pady=2)
        self.scope_buttons = {}
        for i, s in enumerate(("All", "Favorites", "Recent", "Imported")):
            bt = ttk.Button(sc, text=s, style="Tool.TButton", command=lambda s=s: self.set_scope(s))
            bt.grid(row=0, column=i, sticky="ew", padx=1)
            sc.columnconfigure(i, weight=1, uniform="scope")
            self.scope_buttons[s] = bt
        grid = ttk.Frame(p)
        grid.pack(fill="x", pady=4)
        cats = ["All"] + [c for c, _ in self.fonts.categories()]
        self.cat_var = tk.StringVar(value="All")
        self.kind_var = tk.StringVar(value="All")
        self.src_var = tk.StringVar(value="All")
        for i, (lab, var, vals) in enumerate((("Category", self.cat_var, cats),
                                              ("Type", self.kind_var, ["All", "genuine", "figlet", "toilet", "raster"]),
                                              ("Source", self.src_var, ["All"] + self.fonts.sources() + ["imported"]))):
            ttk.Label(grid, text=lab, style="Muted.TLabel").grid(row=i, column=0, sticky="w", pady=1)
            cb = ttk.Combobox(grid, textvariable=var, values=vals, state="readonly", width=20)
            cb.grid(row=i, column=1, sticky="ew", pady=1, padx=(6, 0))
            var.trace_add("write", lambda *a: self.refresh_fonts())
        grid.columnconfigure(1, weight=1)
        hrow = ttk.Frame(p)
        hrow.pack(fill="x", pady=2)
        ttk.Label(hrow, text="Height", style="Muted.TLabel").pack(side="left")
        self.hmin_var = tk.IntVar(value=0)
        self.hmax_var = tk.IntVar(value=99)
        for v in (self.hmin_var, self.hmax_var):
            sp = ttk.Spinbox(hrow, from_=0, to=99, width=4, textvariable=v, command=self.refresh_fonts)
            sp.pack(side="left", padx=3)
            sp.bind("<KeyRelease>", lambda e: self._debounced_refresh())
        self.clear_lic_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(hrow, text="Clear license", variable=self.clear_lic_var, command=self.refresh_fonts).pack(side="right")
        self.count_var = tk.StringVar()
        ttk.Label(p, textvariable=self.count_var, style="Muted.TLabel").pack(anchor="w", pady=(6, 2))
        lf = ttk.Frame(p)
        lf.pack(fill="both", expand=True)
        self.font_list = tk.Listbox(lf, bg=C["bg2"], fg=C["text"], selectbackground=C["sel"], selectforeground=C["text"],
                                    highlightthickness=0, borderwidth=0, activestyle="none", exportselection=False,
                                    font=(self.ui, 10))
        sb = ttk.Scrollbar(lf, command=self.font_list.yview)
        self.font_list.configure(yscrollcommand=sb.set)
        self.font_list.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.font_list.bind("<<ListboxSelect>>", self._on_font_select)
        self.font_list.bind("<Double-Button-1>", lambda e: self.toggle_favorite())
        self.font_list.bind("<Up>", lambda e: self._nudge(-1))
        self.font_list.bind("<Down>", lambda e: self._nudge(1))
        acts = ttk.Frame(p)
        acts.pack(fill="x", pady=(6, 0))
        for i, (lab, cmd) in enumerate((("★ Favorite", self.toggle_favorite), ("Random", self.random_font),
                                         ("+ Compare", self.add_compare), ("Import…", self.import_fonts),
                                         ("Import ZIP…", self.import_zip), ("Manage…", self.manage_fonts))):
            ttk.Button(acts, text=lab, style="Tool.TButton", command=cmd).grid(row=i // 3, column=i % 3, sticky="ew", padx=1, pady=1)
        for c in range(3):
            acts.columnconfigure(c, weight=1)

    # -------------------------------------------------------- center panel
    def _build_center(self) -> None:
        p = self.center
        self.input_frame = ttk.Frame(p, style="Card.TFrame", padding=8)
        self.input_frame.pack(fill="x")
        hdr = ttk.Frame(self.input_frame, style="Card.TFrame")
        hdr.pack(fill="x")
        self.input_label = ttk.Label(hdr, text="YOUR TEXT", style="Head.TLabel", background=C["bg2"])
        self.input_label.pack(side="left")
        self.char_var = tk.StringVar()
        ttk.Label(hdr, textvariable=self.char_var, style="Head.TLabel", background=C["bg2"]).pack(side="right")
        self.text_in = tk.Text(self.input_frame, height=3, bg=C["bg2"], fg=C["text"], insertbackground=C["text"],
                               relief="flat", font=(self.ui, 13), wrap="word", undo=True, highlightthickness=0,
                               padx=4, pady=4)
        self.text_in.pack(fill="x", pady=(4, 0))
        self.text_in.insert("1.0", "LeerBox")
        self.text_in.bind("<<Modified>>", self._on_text_modified)

        tb = ttk.Frame(p, style="Bg0.TFrame", padding=(0, 8, 0, 6))
        tb.pack(fill="x")
        self.view_buttons = {}
        for key, label in (("preview", "Preview"), ("gallery", "All-font gallery"), ("compare", "Compare")):
            bt = ttk.Button(tb, text=label, style="Tab.TButton", command=lambda k=key: self.set_view(k))
            bt.pack(side="left", padx=1)
            self.view_buttons[key] = bt
        for lab, cmd in (("⛶", self.fullscreen), ("Fit", self.fit_zoom), ("+", lambda: self.set_zoom(self.zoom * 1.15)),
                         ("−", lambda: self.set_zoom(self.zoom / 1.15))):
            ttk.Button(tb, text=lab, style="Tool.TButton", width=4 if len(lab) < 3 else 5, command=cmd).pack(side="right", padx=1)
        self.zoom_var = tk.StringVar()
        ttk.Label(tb, textvariable=self.zoom_var, style="Bar.TLabel", width=6).pack(side="right")
        self.autofit = tk.BooleanVar(value=True)
        ttk.Checkbutton(tb, text="Auto-fit", variable=self.autofit, command=self.request_render,
                        style="Bar.TCheckbutton").pack(side="right", padx=4)
        self.graphic = tk.BooleanVar(value=HAVE_IMAGETK)
        self.graphic_btn = ttk.Checkbutton(tb, text="Graphic", variable=self.graphic, command=self.request_render,
                                           style="Bar.TCheckbutton")
        if HAVE_IMAGETK:
            self.graphic_btn.pack(side="right", padx=4)
        ttk.Button(tb, text="Copy", style="Tool.TButton", command=self.copy_text).pack(side="right", padx=6)
        self.view_toolbar = tb

        self.view_host = ttk.Frame(p, style="Bg0.TFrame")
        self.view_host.pack(fill="both", expand=True)
        # preview
        self.preview_frame = ttk.Frame(self.view_host, style="Bg0.TFrame")
        self.preview = tk.Text(self.preview_frame, bg=C["bg0"], fg=C["text"], relief="flat", wrap="none",
                               font=self.preview_font, highlightthickness=1, highlightbackground=C["line"],
                               highlightcolor=C["line"], padx=16, pady=14, cursor="arrow", insertwidth=0)
        ys = ttk.Scrollbar(self.preview_frame, command=self.preview.yview)
        xs = ttk.Scrollbar(self.preview_frame, orient="horizontal", command=self.preview.xview)
        self.preview.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        self.preview.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        self.preview_frame.rowconfigure(0, weight=1)
        self.preview_frame.columnconfigure(0, weight=1)
        self.preview.bind("<Key>", lambda e: "break" if e.keysym not in ("c", "C", "a", "A") or not (e.state & 4) else None)
        self.gcanvas = tk.Canvas(self.preview_frame, bg=C["bg0"], highlightthickness=1, highlightbackground=C["line"])
        self.gcanvas.grid(row=0, column=0, sticky="nsew")
        self.gcanvas.bind("<MouseWheel>", lambda e: self.gcanvas.yview_scroll(int(-e.delta / 40), "units"))
        self._gimg = None
        self._preview_ys, self._preview_xs = ys, xs
        self.preview.tkraise()
        # gallery
        self.gallery_frame = ttk.Frame(self.view_host, style="Bg0.TFrame")
        self.gallery = tk.Canvas(self.gallery_frame, bg=C["bg0"], highlightthickness=0)
        gs = ttk.Scrollbar(self.gallery_frame, command=self._gallery_scroll)
        self.gallery.configure(yscrollcommand=gs.set)
        self.gallery.pack(side="left", fill="both", expand=True)
        gs.pack(side="right", fill="y")
        self.gallery.bind("<Configure>", lambda e: self.layout_gallery())
        self.gallery.bind("<MouseWheel>", lambda e: (self.gallery.yview_scroll(int(-e.delta / 40), "units"), self.paint_gallery()))
        self.gallery.bind("<Button-1>", self._gallery_click)
        # compare
        self.compare_frame = ttk.Frame(self.view_host, style="Bg0.TFrame")
        cbar = ttk.Frame(self.compare_frame, style="Bg0.TFrame")
        cbar.pack(fill="x", pady=(0, 4))
        self.compare_var = tk.StringVar(value="Add fonts with “+ Compare” (up to 6).")
        ttk.Label(cbar, textvariable=self.compare_var, style="Bar.TLabel").pack(side="left")
        ttk.Button(cbar, text="Clear", style="Tool.TButton", command=self.clear_compare).pack(side="right")
        self.compare_text = tk.Text(self.compare_frame, bg=C["bg0"], fg=C["text"], relief="flat", wrap="none",
                                    font=self.preview_font, highlightthickness=1, highlightbackground=C["line"],
                                    padx=16, pady=12)
        self.compare_text.pack(fill="both", expand=True)
        # unicode / encoder / boxes views (text-based panels)
        self.unicode_frame = ttk.Frame(self.view_host, style="Bg0.TFrame")
        self.uni_tree = ttk.Treeview(self.unicode_frame, columns=("style", "out"), show="headings")
        self.uni_tree.heading("style", text="Algorithmic style")
        self.uni_tree.heading("out", text="Output (double-click to copy)")
        self.uni_tree.column("style", width=200, stretch=False)
        self.uni_tree.column("out", width=600)
        self.uni_tree.pack(fill="both", expand=True)
        self.uni_tree.bind("<Double-1>", self._copy_unicode_row)
        self.tool_frame = ttk.Frame(self.view_host, style="Bg0.TFrame")
        self.tool_out = tk.Text(self.tool_frame, bg=C["bg0"], fg=C["text"], relief="flat", wrap="none",
                                font=self.preview_font, highlightthickness=1, highlightbackground=C["line"], padx=14, pady=12)
        self.tool_out.pack(fill="both", expand=True)
        self.set_view("preview")

    # --------------------------------------------------------- right panel
    def _build_right(self) -> None:
        nb = ttk.Notebook(self.rightp)
        nb.pack(fill="both", expand=True)
        self.nb = nb
        self.tab_layout = self._scroll_tab(nb, "Layout")
        self.tab_fx = ttk.Frame(nb, padding=8)
        nb.add(self.tab_fx, text="Effects")
        self.tab_export = self._scroll_tab(nb, "Export")
        self.tab_info = ttk.Frame(nb, padding=8)
        nb.add(self.tab_info, text="Info")
        self.tab_tool = ttk.Frame(nb, padding=8)
        nb.add(self.tab_tool, text="Tool")
        self._build_layout_tab()
        self._build_fx_tab()
        self._build_export_tab()
        self._build_info_tab()

    def _scroll_tab(self, nb, title):
        outer = ttk.Frame(nb)
        nb.add(outer, text=title)
        cv = tk.Canvas(outer, bg=C["bg1"], highlightthickness=0, width=320)
        sb = ttk.Scrollbar(outer, command=cv.yview)
        inner = ttk.Frame(cv, padding=8)
        inner.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
        win = cv.create_window(0, 0, window=inner, anchor="nw")
        cv.bind("<Configure>", lambda e: cv.itemconfigure(win, width=e.width))
        cv.configure(yscrollcommand=sb.set)
        cv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        def wheel(e):
            cv.yview_scroll(int(-e.delta / 60), "units")
        inner.bind("<Enter>", lambda e: cv.bind_all("<MouseWheel>", wheel))
        inner.bind("<Leave>", lambda e: cv.unbind_all("<MouseWheel>"))
        return inner

    def _section(self, parent, title):
        ttk.Label(parent, text=title, style="Head.TLabel").pack(anchor="w", pady=(10, 3))
        f = ttk.Frame(parent)
        f.pack(fill="x")
        f.columnconfigure(1, weight=1)
        return f

    def _row(self, f, r, label, widget):
        ttk.Label(f, text=label, style="Muted.TLabel").grid(row=r, column=0, sticky="w", pady=2, padx=(0, 8))
        widget.grid(row=r, column=1, sticky="ew", pady=2)
        return widget

    def _build_layout_tab(self) -> None:
        p = self.tab_layout
        self.ovars: dict[str, tk.Variable] = {}

        def combo(f, r, key, label, vals):
            v = tk.StringVar(value=str(getattr(self.opts, key)))
            self.ovars[key] = v
            self._row(f, r, label, ttk.Combobox(f, textvariable=v, values=vals, state="readonly", width=14))
            v.trace_add("write", lambda *a: self._opts_changed())

        def spin(f, r, key, label, lo, hi):
            v = tk.IntVar(value=getattr(self.opts, key))
            self.ovars[key] = v
            sp = ttk.Spinbox(f, from_=lo, to=hi, textvariable=v, width=8, command=self._opts_changed)
            sp.bind("<KeyRelease>", lambda e: self._opts_changed())
            self._row(f, r, label, sp)

        def check(f, r, key, label):
            v = tk.BooleanVar(value=getattr(self.opts, key))
            self.ovars[key] = v
            ttk.Checkbutton(f, text=label, variable=v, command=self._opts_changed).grid(row=r, column=0, columnspan=2, sticky="w", pady=1)

        f = self._section(p, "FIGLET LAYOUT")
        combo(f, 0, "h_layout", "Horizontal", ["default", "full", "fitted", "smush", "universal"])
        combo(f, 1, "v_layout", "Vertical", ["default", "full", "fitted", "smush", "universal"])
        combo(f, 2, "align", "Alignment", ["left", "center", "right"])
        combo(f, 3, "direction", "Direction", ["auto", "ltr", "rtl"])
        spin(f, 4, "width", "Wrap width (0=off)", 0, 1000)
        spin(f, 5, "letter_spacing", "Letter spacing", 0, 20)
        spin(f, 6, "line_spacing", "Line spacing", 0, 20)
        combo(f, 7, "missing", "Missing chars", ["skip", "question", "zero"])
        check(f, 8, "fallback", "Unicode fallback (é→e, case swap)")
        f = self._section(p, "RASTER / ARABIC FONTS")
        combo(f, 0, "raster_mode", "Pixel mapping", ["block", "half", "quarter", "braille", "ascii", "shade", "dots",
                                                     "money", "binary", "at", "star", "custom"])
        v = tk.StringVar(value=self.opts.raster_char)
        self.ovars["raster_char"] = v
        en = ttk.Entry(f, textvariable=v, width=6)
        self._row(f, 1, "Custom character", en)
        v.trace_add("write", lambda *a: self._opts_changed())
        spin(f, 2, "raster_scale", "Pixel scale", 1, 6)
        spin(f, 3, "raster_aspect", "Horizontal stretch", 1, 3)
        check(f, 4, "raster_invert", "Invert pixels")
        f = self._section(p, "ARABIC ENGINE")
        check(f, 0, "arabic_shaping", "Contextual shaping")
        check(f, 1, "ligatures", "Lam-alef ligatures")
        check(f, 2, "diacritics", "Keep diacritics (harakat)")
        combo(f, 3, "digits", "Digits", ["keep", "western", "arabic", "persian"])
        ttk.Label(p, text="Raster Arabic fonts preserve visual appearance; the Unicode tab’s "
                          "“visual text” keeps presentation forms for non-shaping terminals.",
                  style="Muted.TLabel", wraplength=290, justify="left").pack(anchor="w", pady=(8, 0))
        f = self._section(p, "DESIGN PRESETS")
        self.curated = curated_designs(self.fonts)
        self.curated_var = tk.StringVar()
        cb = ttk.Combobox(f, textvariable=self.curated_var, values=[d["name"] for d in self.curated], state="readonly")
        self._row(f, 0, "Curated", cb)
        cb.bind("<<ComboboxSelected>>", lambda e: self.apply_curated())
        self.preset_var = tk.StringVar()
        self.preset_cb = ttk.Combobox(f, textvariable=self.preset_var, values=sorted(self.settings.data["presets"]), state="readonly")
        self._row(f, 1, "My presets", self.preset_cb)
        self.preset_cb.bind("<<ComboboxSelected>>", lambda e: self.load_preset())
        bf = ttk.Frame(f)
        bf.grid(row=2, column=0, columnspan=2, sticky="ew", pady=4)
        for lab, cmd in (("Random design", self.random_design), ("Save preset…", self.save_preset), ("Delete preset", self.delete_preset)):
            ttk.Button(bf, text=lab, style="Tool.TButton", command=cmd).pack(side="left", expand=True, fill="x", padx=1)

    def _opts_changed(self) -> None:
        for k, v in self.ovars.items():
            try:
                val = v.get()
            except (tk.TclError, ValueError):
                continue
            cur = getattr(self.opts, k)
            if isinstance(cur, bool):
                val = bool(val)
            elif isinstance(cur, int):
                try:
                    val = int(val)
                except (TypeError, ValueError):
                    continue
            setattr(self.opts, k, val)
        self.request_render()

    # ------------------------------------------------------------ effects
    def _build_fx_tab(self) -> None:
        p = self.tab_fx
        ttk.Label(p, text="EFFECTS PIPELINE (applied top → bottom)", style="Head.TLabel").pack(anchor="w")
        lf = ttk.Frame(p)
        lf.pack(fill="x", pady=4)
        self.fx_list = tk.Listbox(lf, height=7, bg=C["bg2"], fg=C["text"], selectbackground=C["sel"],
                                  highlightthickness=0, borderwidth=0, activestyle="none", exportselection=False)
        self.fx_list.pack(fill="x")
        self.fx_list.bind("<<ListboxSelect>>", lambda e: self._fx_edit())
        self.fx_list.bind("<Double-Button-1>", lambda e: self._fx_toggle())
        bf = ttk.Frame(p)
        bf.pack(fill="x")
        self.fx_add_mb = ttk.Menubutton(bf, text="＋ Add effect")
        menu = tk.Menu(self.fx_add_mb, tearoff=0)
        groups = {"color": "Colour", "text": "Text (plain-text safe)", "graphic": "Graphic only (HTML/SVG/PNG)"}
        for g, title in groups.items():
            sub = tk.Menu(menu, tearoff=0)
            for k, (kind, label) in EFFECT_INFO.items():
                if kind == g:
                    sub.add_command(label=label, command=lambda k=k: self.add_effect(k))
            menu.add_cascade(label=title, menu=sub)
        self.fx_add_mb["menu"] = menu
        self.fx_add_mb.pack(side="left", fill="x", expand=True, padx=1)
        for lab, cmd in (("▲", lambda: self._fx_move(-1)), ("▼", lambda: self._fx_move(1)),
                         ("On/Off", self._fx_toggle), ("✕", self._fx_remove)):
            ttk.Button(bf, text=lab, style="Tool.TButton", command=cmd, width=6 if len(lab) > 2 else 3).pack(side="left", padx=1)
        self.fx_repr_var = tk.StringVar()
        ttk.Label(p, textvariable=self.fx_repr_var, style="Muted.TLabel", wraplength=300, justify="left").pack(anchor="w", pady=4)
        ttk.Label(p, text="PARAMETERS", style="Head.TLabel").pack(anchor="w", pady=(6, 2))
        self.fx_params = ttk.Frame(p)
        self.fx_params.pack(fill="both", expand=True)
        self.fx_params.columnconfigure(1, weight=1)

    def _fx_refresh_list(self, select: int | None = None) -> None:
        self.fx_list.delete(0, "end")
        for e in self.effects:
            kind, label = EFFECT_INFO.get(e["type"], ("text", e["type"]))
            mark = "●" if e.get("enabled", True) else "○"
            tag = {"color": "colour", "graphic": "graphic", "text": "text"}[kind]
            self.fx_list.insert("end", f" {mark}  {label}   · {tag}")
        if select is not None and 0 <= select < len(self.effects):
            self.fx_list.selection_set(select)
            self.fx_list.see(select)
        rep = pipeline_representation(self.effects)
        if rep["lossy_in_text"]:
            self.fx_repr_var.set("Not representable in plain text: " + ", ".join(rep["lossy_in_text"])
                                 + ". These survive in ANSI/HTML/SVG/PNG exports.")
        else:
            self.fx_repr_var.set("All enabled effects are plain-text safe." if self.effects else "No effects. Add one above.")
        self._fx_edit()

    def add_effect(self, kind: str) -> None:
        self.effects.append(new_effect(kind))
        self._fx_refresh_list(len(self.effects) - 1)
        self.request_render()

    def _fx_sel(self) -> int | None:
        s = self.fx_list.curselection()
        return s[0] if s else None

    def _fx_move(self, d: int) -> None:
        i = self._fx_sel()
        if i is None or not 0 <= i + d < len(self.effects):
            return
        self.effects[i], self.effects[i + d] = self.effects[i + d], self.effects[i]
        self._fx_refresh_list(i + d)
        self.request_render()

    def _fx_toggle(self) -> None:
        i = self._fx_sel()
        if i is None:
            return
        self.effects[i]["enabled"] = not self.effects[i].get("enabled", True)
        self._fx_refresh_list(i)
        self.request_render()

    def _fx_remove(self) -> None:
        i = self._fx_sel()
        if i is None:
            return
        del self.effects[i]
        self._fx_refresh_list(min(i, len(self.effects) - 1))
        self.request_render()

    def _fx_edit(self) -> None:
        for w in self.fx_params.winfo_children():
            w.destroy()
        i = self._fx_sel()
        if i is None:
            ttk.Label(self.fx_params, text="Select an effect to edit its parameters.", style="Muted.TLabel").grid(row=0, column=0)
            return
        e = self.effects[i]
        r = 0
        for key, default in FX_DEFAULTS[e["type"]].items():
            ttk.Label(self.fx_params, text=key.replace("_", " ").capitalize(), style="Muted.TLabel").grid(row=r, column=0, sticky="w", pady=2, padx=(0, 8))
            val = e.get(key, default)

            def setter(v, key=key, e=e):
                e[key] = v
                self.request_render()
            if key in COLOR_KEYS:
                fr = ttk.Frame(self.fx_params)
                var = tk.StringVar(value=val or "")
                ent = ttk.Entry(fr, textvariable=var, width=10)
                ent.pack(side="left", fill="x", expand=True)
                sw = tk.Label(fr, width=3, bg=val if val else C["bg3"], relief="flat")
                sw.pack(side="left", padx=4)
                def pick(var=var, sw=sw, setter=setter):
                    c = colorchooser.askcolor(var.get() or "#7c8cff", parent=self.root)[1]
                    if c:
                        var.set(c)
                def on_var(*a, var=var, sw=sw, setter=setter):
                    v = var.get().strip()
                    try:
                        if v:
                            hex_to_rgb(v)
                            sw.configure(bg=v if v.startswith("#") else "#" + v)
                        setter(v)
                    except ValueError:
                        pass
                var.trace_add("write", on_var)
                ttk.Button(fr, text="…", style="Tool.TButton", width=2, command=pick).pack(side="left")
                fr.grid(row=r, column=1, sticky="ew", pady=2)
                self._fx_widgets.append(var)
            elif key == "stops":
                var = tk.StringVar(value=", ".join(val))
                ent = ttk.Entry(self.fx_params, textvariable=var)
                ent.grid(row=r, column=1, sticky="ew", pady=2)
                def on_stops(*a, var=var, setter=setter):
                    parts = [s.strip() for s in var.get().split(",") if s.strip()]
                    try:
                        for s in parts:
                            hex_to_rgb(s)
                    except ValueError:
                        return
                    if parts:
                        setter(parts)
                var.trace_add("write", on_stops)
                self._fx_widgets.append(var)
                r += 1
                ttk.Label(self.fx_params, text="Comma-separated hex colours (2–16 stops)", style="Muted.TLabel").grid(row=r, column=1, sticky="w")
            elif key in FX_CHOICES:
                var = tk.StringVar(value=str(val))
                cb = ttk.Combobox(self.fx_params, textvariable=var, values=FX_CHOICES[key], state="readonly")
                cb.grid(row=r, column=1, sticky="ew", pady=2)
                var.trace_add("write", lambda *a, var=var, setter=setter, key=key: setter(int(var.get()) if key == "angle" else var.get()))
                self._fx_widgets.append(var)
            elif isinstance(default, bool):
                var = tk.BooleanVar(value=bool(val))
                ttk.Checkbutton(self.fx_params, variable=var, command=lambda var=var, setter=setter: setter(var.get())).grid(row=r, column=1, sticky="w")
                self._fx_widgets.append(var)
            elif isinstance(default, (int, float)):
                isf = isinstance(default, float)
                var = tk.StringVar(value=str(val))
                lo, hi, inc = (0, 1, 0.05) if isf and default <= 1 else (0, 20, 0.5) if isf else (-20, 200, 1)
                sp = ttk.Spinbox(self.fx_params, from_=lo, to=hi, increment=inc, textvariable=var, width=8)
                sp.grid(row=r, column=1, sticky="ew", pady=2)
                def on_num(*a, var=var, setter=setter, isf=isf):
                    try:
                        setter(float(var.get()) if isf else int(float(var.get())))
                    except ValueError:
                        pass
                var.trace_add("write", on_num)
                self._fx_widgets.append(var)
            else:
                var = tk.StringVar(value=str(val))
                ttk.Entry(self.fx_params, textvariable=var).grid(row=r, column=1, sticky="ew", pady=2)
                var.trace_add("write", lambda *a, var=var, setter=setter: setter(var.get()))
                self._fx_widgets.append(var)
            r += 1
        kind, label = EFFECT_INFO[e["type"]]
        note = {"text": "Plain-text effect: preserved in every export.",
                "color": "Colour effect: preserved in ANSI, HTML, SVG and image exports.",
                "graphic": "Graphical effect: only HTML, SVG and image exports (and this preview hint)."}[kind]
        ttk.Label(self.fx_params, text=note, style="Muted.TLabel", wraplength=290, justify="left").grid(row=r, column=0, columnspan=2, sticky="w", pady=(8, 0))

    # ------------------------------------------------------------- export
    def _build_export_tab(self) -> None:
        p = self.tab_export
        self.evars: dict[str, tk.Variable] = {}
        f = self._section(p, "FORMAT")
        self.fmt_var = tk.StringVar(value="png")
        labels = [f"{k} — {v[0]}" for k, v in FORMATS.items()]
        cb = ttk.Combobox(f, values=labels, state="readonly")
        cb.set("png — PNG image")
        cb.bind("<<ComboboxSelected>>", lambda e: self.fmt_var.set(cb.get().split(" ")[0]))
        self._row(f, 0, "Format", cb)
        ttk.Button(f, text="Export…  (Ctrl+E)", style="Accent.TButton", command=self.export_dialog).grid(row=1, column=0, columnspan=2, sticky="ew", pady=6)
        f = self._section(p, "GRAPHICS SETTINGS")

        def ent(r, key, label, kind=str):
            v = tk.StringVar(value=str(getattr(self.exp, key)))
            self.evars[key] = v
            self._row(f, r, label, ttk.Entry(f, textvariable=v, width=10))
        ent(0, "font_size", "Font size (px)")
        ent(1, "scale", "Scale (resolution ×)")
        ent(2, "padding", "Padding (px)")
        ent(3, "line_height", "Line height")
        ent(4, "background", "Background")
        ent(5, "foreground", "Default text colour")
        ent(6, "jpeg_quality", "JPEG/WebP quality")
        v = tk.BooleanVar(value=self.exp.transparent)
        self.evars["transparent"] = v
        ttk.Checkbutton(f, text="Transparent background (PNG, WebP, SVG, HTML)", variable=v).grid(row=7, column=0, columnspan=2, sticky="w")
        v = tk.BooleanVar(value=self.exp.embed_font)
        self.evars["embed_font"] = v
        ttk.Checkbutton(f, text="Embed DejaVu Sans Mono in HTML/SVG", variable=v).grid(row=8, column=0, columnspan=2, sticky="w")
        v = tk.StringVar(value=self.exp.ansi_mode)
        self.evars["ansi_mode"] = v
        self._row(f, 9, "ANSI colours", ttk.Combobox(f, textvariable=v, values=["truecolor", "256", "16", "none"], state="readonly", width=10))
        if not HAVE_PILLOW:
            ttk.Label(f, text="Pillow not installed: PNG/BMP use the built-in bitmap renderer; JPEG/WebP need Pillow.",
                      style="Muted.TLabel", wraplength=280).grid(row=10, column=0, columnspan=2, sticky="w")
        f = self._section(p, "CLIPBOARD")
        bf = ttk.Frame(f)
        bf.grid(row=0, column=0, columnspan=2, sticky="ew")
        for i, (lab, cmd) in enumerate((("Copy text", self.copy_text), ("Copy ANSI", self.copy_ansi),
                                         ("Copy HTML", self.copy_html), ("Copy Markdown", self.copy_md))):
            ttk.Button(bf, text=lab, style="Tool.TButton", command=cmd).grid(row=i // 2, column=i % 2, sticky="ew", padx=1, pady=1)
        bf.columnconfigure(0, weight=1)
        bf.columnconfigure(1, weight=1)
        self.code_var = tk.StringVar(value="python")
        self._row(f, 1, "Source code", ttk.Combobox(f, textvariable=self.code_var, values=list(CODE_LANGS), state="readonly", width=10))
        ttk.Button(f, text="Copy as escaped source code", style="Tool.TButton", command=self.copy_code).grid(row=2, column=0, columnspan=2, sticky="ew", pady=2)
        f = self._section(p, "BATCH EXPORT")
        self.batch_scope = tk.StringVar(value="Favorites")
        self._row(f, 0, "Fonts", ttk.Combobox(f, textvariable=self.batch_scope, values=["Favorites", "Compare set", "Current filter"], state="readonly", width=14))
        self.batch_fmts = tk.StringVar(value="txt,png")
        self._row(f, 1, "Formats", ttk.Entry(f, textvariable=self.batch_fmts))
        ttk.Button(f, text="Batch export to folder…", style="Tool.TButton", command=self.batch_export).grid(row=2, column=0, columnspan=2, sticky="ew", pady=4)

    def _read_export_settings(self) -> ExportSettings:
        d = {}
        for k, v in self.evars.items():
            try:
                d[k] = v.get()
            except tk.TclError:
                pass
        for k in ("background", "foreground"):
            try:
                hex_to_rgb(str(d.get(k, "")))
            except ValueError:
                d.pop(k, None)
        self.exp = ExportSettings.from_dict(d)
        return self.exp

    # --------------------------------------------------------------- info
    def _build_info_tab(self) -> None:
        p = self.tab_info
        self.info_text = tk.Text(p, height=16, bg=C["bg2"], fg=C["text"], relief="flat", wrap="word",
                                 font=(self.ui, 9), highlightthickness=0, padx=8, pady=6)
        self.info_text.pack(fill="x")
        ttk.Label(p, text="SMART RECOMMENDATIONS", style="Head.TLabel").pack(anchor="w", pady=(10, 2))
        rf = ttk.Frame(p)
        rf.pack(fill="x")
        self.rec_target = tk.StringVar(value="terminal")
        ttk.Combobox(rf, textvariable=self.rec_target, values=["terminal", "wide", "compact", "banner"], state="readonly", width=10).pack(side="left")
        ttk.Button(rf, text="Recommend fonts", style="Tool.TButton", command=self.run_recommend).pack(side="left", padx=4)
        self.rec_tree = ttk.Treeview(p, columns=("font", "size"), show="headings", height=10)
        self.rec_tree.heading("font", text="Font")
        self.rec_tree.heading("size", text="Cols × rows")
        self.rec_tree.column("size", width=90, stretch=False)
        self.rec_tree.pack(fill="both", expand=True, pady=4)
        self.rec_tree.bind("<<TreeviewSelect>>", self._rec_pick)

    # ============================================================ behaviour
    def status(self, msg: str, level: str = "info") -> None:
        self.status_var.set(msg)
        self.status_lbl.configure(foreground={"info": C["muted"], "ok": C["ok"], "warn": C["warn"], "err": C["err"]}[level])
        if level in ("warn", "err"):
            LOG.warning(msg)

    def get_text(self) -> str:
        return self.text_in.get("1.0", "end-1c")

    def _on_text_modified(self, _e=None) -> None:
        if self.text_in.edit_modified():
            self.text_in.edit_modified(False)
            t = self.get_text()
            self.char_var.set(f"{len(t)} chars" + (" · Arabic detected" if contains_arabic(t) else ""))
            if len(t) > 5000:
                self.status("Input is limited to 5000 characters; extra text is ignored.", "warn")
            self.request_render()

    # ------------------------------------------------------------- modes
    def show_workspace(self, name: str) -> bool:
        """Switch between the Text-to-Art, Image-to-Art and Animation-to-Art workspaces."""
        if name != "text" and name not in self.workspaces:
            from ..imgcore import np as _np
            missing = [n for n, ok in (("NumPy", _np is not None), ("Pillow", HAVE_IMAGETK)) if not ok]
            if missing:
                messagebox.showinfo("Image Studio", "The Image and Animation Studios need " + " and ".join(missing)
                                    + ".\nInstall with:  pip install pillow numpy", parent=self.root)
                return False
            if "image" not in self.workspaces:
                self.workspaces["image"] = ImageWorkspace(self.root, self, C)
            if name == "animation":
                self.workspaces["animation"] = AnimationWorkspace(self.root, self, C, self.workspaces["image"])
        self.paned.pack_forget()
        for w in self.workspaces.values():
            w.pack_forget()
        target = self.paned if name == "text" else self.workspaces[name]
        target.pack(fill="both", expand=True, before=self.bar)
        if name != "text":
            target.after(30, target.fix_sash)
            self.status_var.set({"image": "Image-to-Art Studio", "animation": "Animation-to-Art Studio"}[name]
                                + " — shares export settings, effects, presets and projects with the Text Studio")
            self.size_var.set("")
        return True

    def set_mode(self, mode: str) -> None:
        if mode in ("image", "animation"):
            if self.show_workspace(mode):
                self.mode = mode
                for k, b in self.mode_buttons.items():
                    b.configure(style="TabOn.TButton" if k == mode else "Tab.TButton")
            return
        if self.mode in ("image", "animation"):
            self.show_workspace("text")
        self.mode = mode
        for k, b in self.mode_buttons.items():
            b.configure(style="TabOn.TButton" if k == mode else "Tab.TButton")
        labels = {"text": "YOUR TEXT", "unicode": "TEXT TO STYLE", "image": "IMAGE ART (open an image in the Tool tab)",
                  "encode": "TEXT TO ENCODE / DECODE", "boxes": "BOX / BANNER TEXT"}
        self.input_label.configure(text=labels[mode])
        self._build_tool_tab()
        for k, b in self.view_buttons.items():
            b.state(["!disabled"] if mode == "text" else ["disabled"])
        if mode == "text":
            self.set_view(self.view if self.view in ("preview", "gallery", "compare") else "preview")
        elif mode == "unicode":
            self._show_view_frame(self.unicode_frame)
        elif mode in ("encode", "boxes"):
            self._show_view_frame(self.tool_frame)
        elif mode == "image":
            self._show_view_frame(self.preview_frame)
        self.request_render()

    def _show_view_frame(self, frame) -> None:
        for f in (self.preview_frame, self.gallery_frame, self.compare_frame, self.unicode_frame, self.tool_frame):
            f.pack_forget()
        frame.pack(fill="both", expand=True)

    def set_view(self, view: str) -> None:
        if self.mode != "text":
            self.set_mode("text")
        self.view = view
        for k, b in self.view_buttons.items():
            b.configure(style="TabOn.TButton" if k == view else "Tab.TButton")
        self._show_view_frame({"preview": self.preview_frame, "gallery": self.gallery_frame, "compare": self.compare_frame}[view])
        if view == "gallery":
            self.start_gallery()
        elif view == "compare":
            self.render_compare()
        else:
            self.request_render()

    def _build_tool_tab(self) -> None:
        for w in self.tab_tool.winfo_children():
            w.destroy()
        p = self.tab_tool
        self.tvars: dict[str, tk.Variable] = {}
        if self.mode == "image":
            ttk.Label(p, text="IMAGE → ASCII / UNICODE / ANSI", style="Head.TLabel").pack(anchor="w")
            ttk.Button(p, text="Open image…", style="Accent.TButton", command=self.open_image).pack(fill="x", pady=6)
            f = ttk.Frame(p)
            f.pack(fill="x")
            f.columnconfigure(1, weight=1)
            specs = [("cols", "Width (columns)", "100"), ("mode", "Mode", "ascii"), ("ramp", "Character ramp", "standard"),
                     ("brightness", "Brightness (−1…1)", "0"), ("contrast", "Contrast (0…3)", "1"),
                     ("gamma", "Gamma", "1"), ("dither", "Dithering", "none"), ("color", "Colour", "none"),
                     ("threshold", "Threshold (1-bit)", "0.5"), ("aspect", "Cell aspect", "0.5")]
            choices = {"mode": ["ascii", "blocks", "half", "quarter", "braille"], "ramp": list(RAMPS),
                       "dither": ["none", "floyd", "atkinson", "ordered"], "color": ["none", "truecolor"]}
            for r, (k, lab, dv) in enumerate(specs):
                v = tk.StringVar(value=dv)
                self.tvars[k] = v
                if k in choices:
                    w = ttk.Combobox(f, textvariable=v, values=choices[k], state="normal" if k == "ramp" else "readonly")
                else:
                    w = ttk.Entry(f, textvariable=v, width=8)
                self._row(f, r, lab, w)
                v.trace_add("write", lambda *a: self.request_render())
            v = tk.BooleanVar(value=False)
            self.tvars["invert"] = v
            ttk.Checkbutton(f, text="Invert", variable=v, command=self.request_render).grid(row=len(specs), column=0, sticky="w")
            ttk.Label(p, text="Images are processed locally and never uploaded. Use the Export tab for TXT/ANSI/HTML/PNG output.",
                      style="Muted.TLabel", wraplength=290, justify="left").pack(anchor="w", pady=8)
        elif self.mode == "encode":
            ttk.Label(p, text="ENCODERS", style="Head.TLabel").pack(anchor="w")
            v = tk.StringVar(value="binary")
            self.tvars["enc"] = v
            ttk.Combobox(p, textvariable=v, values=list(ENCODINGS), state="readonly").pack(fill="x", pady=4)
            v.trace_add("write", lambda *a: self.request_render())
            d = tk.BooleanVar(value=False)
            self.tvars["decode"] = d
            ttk.Checkbutton(p, text="Decode instead of encode (binary, hex, morse, base64)", variable=d,
                            command=self.request_render).pack(anchor="w")
        elif self.mode == "boxes":
            ttk.Label(p, text="BOXES, BANNERS & HEADERS", style="Head.TLabel").pack(anchor="w")
            f = ttk.Frame(p)
            f.pack(fill="x")
            f.columnconfigure(1, weight=1)
            specs = [("kind", "Generator", "Decorative text box", ["Decorative text box", "Terminal banner",
                      "GitHub README banner", "CLI application header"]),
                     ("style", "Box style", "rounded", list(BOX_STYLES)), ("align", "Alignment", "center", ["left", "center", "right"]),
                     ("padding", "Padding", "1", None), ("title", "Title", "", None),
                     ("lang", "Header language", "python", list(CODE_LANGS))]
            for r, (k, lab, dv, vals) in enumerate(specs):
                v = tk.StringVar(value=dv)
                self.tvars[k] = v
                w = ttk.Combobox(f, textvariable=v, values=vals, state="readonly") if vals else ttk.Entry(f, textvariable=v)
                self._row(f, r, lab, w)
                v.trace_add("write", lambda *a: self.request_render())
            ttk.Label(p, text="Banners and headers use the font, layout and effects selected for Text Art.",
                      style="Muted.TLabel", wraplength=290).pack(anchor="w", pady=8)
        elif self.mode == "unicode":
            ttk.Label(p, text="UNICODE STYLES", style="Head.TLabel").pack(anchor="w")
            ttk.Label(p, text="Algorithmic styles substitute Unicode characters (Mathematical Alphanumeric Symbols, "
                              "enclosed and full-width forms). They are not fonts and are counted separately.\n\n"
                              "For Arabic input an extra row shows visual-order presentation forms for terminals "
                              "that cannot shape Arabic (appearance preserved, semantics lost).",
                      style="Muted.TLabel", wraplength=290, justify="left").pack(anchor="w", pady=6)
        else:
            ttk.Label(p, text="Tools for the current mode appear here.", style="Muted.TLabel").pack(anchor="w")

    # -------------------------------------------------------------- fonts
    def set_scope(self, scope: str) -> None:
        self.scope_var.set(scope)
        for k, b in self.scope_buttons.items():
            b.configure(style="ScopeOn.TButton" if k == scope else "Tool.TButton")
        self.refresh_fonts()

    def _debounced_refresh(self) -> None:
        if self._search_debounce:
            self.root.after_cancel(self._search_debounce)
        self._search_debounce = self.root.after(140, self.refresh_fonts)

    def refresh_fonts(self) -> None:
        scope = self.scope_var.get()
        ids = None
        if scope == "Favorites":
            ids = [f for f in self.settings.data["favorites"] if f in self.fonts.entries]
        elif scope == "Recent":
            ids = [f for f in self.settings.data["recents"] if f in self.fonts.entries]
        elif scope == "Imported":
            ids = [f for f, e in self.fonts.entries.items() if not e.builtin]
        try:
            hmin, hmax = int(self.hmin_var.get()), int(self.hmax_var.get())
        except (tk.TclError, ValueError):
            hmin, hmax = 0, 999
        res = self.fonts.search(self.search_var.get(), category=self.cat_var.get(), source=self.src_var.get(),
                                kind=self.kind_var.get(), min_height=hmin, max_height=hmax if hmax < 99 else 999, ids=ids,
                                license_clear=self.clear_lic_var.get())
        if scope == "Recent" and not self.search_var.get():
            order = {f: i for i, f in enumerate(ids or [])}
            res.sort(key=lambda f: order.get(f, 0))
        self.filtered = res
        fav = set(self.settings.data["favorites"])
        self.font_list.delete(0, "end")
        for fid in res:
            e = self.fonts.entries[fid]
            badge = {"figlet": "", "toilet": " · TLF", "raster": " · raster"}[e.type]
            self.font_list.insert("end", f"{'★ ' if fid in fav else '   '}{e.name}{badge}")
        self.count_var.set(f"{len(res)} of {len(self.fonts.entries)} fonts")
        if self.current_fid in res:
            i = res.index(self.current_fid)
            self.font_list.selection_set(i)
            self.font_list.see(i)
            self.root.after_idle(lambda i=i: self.font_list.see(i))  # re-run once the widget is laid out
        if self.view == "gallery" and self.mode == "text":
            self.start_gallery()

    def _on_font_select(self, _e=None) -> None:
        s = self.font_list.curselection()
        if not s:
            return
        self.select_font(self.filtered[s[0]])

    def _nudge(self, d: int):
        s = self.font_list.curselection()
        i = (s[0] if s else -1) + d
        if 0 <= i < len(self.filtered):
            self.font_list.selection_clear(0, "end")
            self.font_list.selection_set(i)
            self.font_list.see(i)
            self.select_font(self.filtered[i])
        return "break"

    def select_font(self, fid: str) -> None:
        if fid not in self.fonts.entries:
            return
        self.current_fid = fid
        self.settings.touch_recent(fid)
        if fid in self.filtered:  # keep the list highlight in sync (gallery clicks, presets, recommendations)
            i = self.filtered.index(fid)
            self.font_list.selection_clear(0, "end")
            self.font_list.selection_set(i)
            self.font_list.see(i)
        if self.mode != "text":
            self.set_mode("text")
        if self.view != "preview":
            self.set_view("preview")
        self.request_render()
        self.update_info()

    def toggle_favorite(self) -> None:
        on = self.settings.toggle_favorite(self.current_fid)
        self.status(("Added to" if on else "Removed from") + " favorites: " + self.fonts.entries[self.current_fid].name, "ok")
        self.refresh_fonts()

    def random_font(self) -> None:
        if self.filtered:
            self.select_font(random.choice(self.filtered))
            self.refresh_fonts()

    def import_fonts(self) -> None:
        paths = filedialog.askopenfilenames(parent=self.root, title="Import FIGlet / TOIlet fonts",
                                            filetypes=[("FIGlet/TOIlet fonts", "*.flf *.tlf"), ("All files", "*.*")])
        if not paths:
            return
        results = []
        for p in paths:
            try:
                if os.path.getsize(p) > 6 * 1024 * 1024:
                    results.append({"ok": False, "file": p, "error": "file too large"})
                    continue
                with open(p, "rb") as fh:
                    results.append(self.fonts.import_bytes(fh.read(), os.path.basename(p)))
            except OSError as exc:
                results.append({"ok": False, "file": p, "error": str(exc)})
        self._report_imports(results)

    def import_zip(self) -> None:
        p = filedialog.askopenfilename(parent=self.root, title="Import ZIP font collection", filetypes=[("ZIP archives", "*.zip")])
        if not p:
            return
        try:
            if os.path.getsize(p) > 64 * 1024 * 1024:
                raise OSError("archive larger than 64 MB")
            with open(p, "rb") as fh:
                data = fh.read()
        except OSError as exc:
            messagebox.showerror("Import ZIP", str(exc), parent=self.root)
            return
        self._report_imports(self.fonts.import_zip(data))

    def _report_imports(self, results: list[dict]) -> None:
        ok = [r for r in results if r.get("ok")]
        bad = [r for r in results if not r.get("ok")]
        if ok:
            self.set_scope("Imported")
            self.select_font(ok[-1]["id"])
        msg = f"Imported {len(ok)} font(s)."
        if bad:
            msg += f" {len(bad)} skipped:\n" + "\n".join(f"• {os.path.basename(r['file'])}: {r['error']}" for r in bad[:25])
            if len(bad) > 25:
                msg += f"\n… and {len(bad) - 25} more"
        (messagebox.showwarning if bad else messagebox.showinfo)("Font import", msg, parent=self.root)
        self.status(msg.split("\n")[0], "ok" if ok else "warn")

    def manage_fonts(self) -> None:
        win = tk.Toplevel(self.root)
        win.title("Font management")
        win.configure(bg=C["bg1"])
        win.geometry("560x420")
        win.transient(self.root)
        ttk.Label(win, text="Imported fonts", style="Head.TLabel").pack(anchor="w", padx=12, pady=(12, 4))
        lb = tk.Listbox(win, bg=C["bg2"], fg=C["text"], selectbackground=C["sel"], highlightthickness=0, borderwidth=0,
                        selectmode="extended")
        lb.pack(fill="both", expand=True, padx=12)
        def fill():
            lb.delete(0, "end")
            win.ids = [f for f, e in self.fonts.entries.items() if not e.builtin]
            for f in win.ids:
                lb.insert("end", self.fonts.entries[f].name)
        fill()
        bf = ttk.Frame(win, padding=12)
        bf.pack(fill="x")
        def remove():
            for i in reversed(lb.curselection()):
                self.fonts.remove_user(win.ids[i])
            fill(); self.refresh_fonts()
        def reset():
            if messagebox.askyesno("Reset", "Remove ALL imported fonts? This deletes them from the LeerBox user folder.", parent=win):
                n = self.fonts.reset_user()
                fill(); self.refresh_fonts()
                self.status(f"Removed {n} imported fonts", "ok")
        def export_coll(scope):
            ids = {"favorites": [f for f in self.settings.data["favorites"] if f in self.fonts.entries],
                   "filter": self.filtered, "imported": win.ids}[scope]
            p = filedialog.asksaveasfilename(parent=win, defaultextension=".zip", filetypes=[("ZIP", "*.zip")],
                                             initialfile=f"leerbox_fonts_{scope}.zip")
            if p:
                try:
                    n = self.fonts.export_collection(ids, p)
                    self.status(f"Exported {n} fonts to {p}", "ok")
                except OSError as exc:
                    messagebox.showerror("Export collection", str(exc), parent=win)
        for lab, cmd in (("Remove selected", remove), ("Reset imports", reset),
                         ("Export favorites…", lambda: export_coll("favorites")),
                         ("Export current filter…", lambda: export_coll("filter")),
                         ("Export imported…", lambda: export_coll("imported"))):
            ttk.Button(bf, text=lab, style="Tool.TButton", command=cmd).pack(side="left", padx=2)

    # -------------------------------------------------------------- render
    def request_render(self, delay: int = 110) -> None:
        if self._debounce:
            self.root.after_cancel(self._debounce)
        self._debounce = self.root.after(delay, self._submit_render)

    def _submit_render(self) -> None:
        self._debounce = None
        self.render_gen += 1
        gen = self.render_gen
        text = self.get_text()[:5000]
        mode = self.mode
        if mode == "text":
            if self.view == "gallery":
                self.start_gallery()
                return
            if self.view == "compare":
                self.render_compare()
                return
            fid, o, fx = self.current_fid, copy.deepcopy(self.opts), copy.deepcopy(self.effects)
            self.worker.submit(("art", gen, self._with_graphic(lambda: self.engine.render(fid, text, o, fx))))
        elif mode in ("image", "animation"):
            return  # handled by the Image / Animation Studio workspaces
        elif mode == "unicode":
            self._render_unicode(text)
        elif mode == "encode":
            self._render_encode(text)
        elif mode == "boxes":
            fid, o, fx = self.current_fid, copy.deepcopy(self.opts), copy.deepcopy(self.effects)
            tv = {k: v.get() for k, v in self.tvars.items()}
            self.worker.submit(("tool", gen, lambda: self._make_box(text, tv, fid, o, fx)))

    def _with_graphic(self, make_art):
        """Wrap a render job: compute zoom (auto-fit) and, in graphic mode, a Pillow image in the worker."""
        want = bool(self.graphic.get()) and HAVE_IMAGETK
        autofit = bool(self.autofit.get())
        zoom = self.zoom
        avail_w = max(200, self.preview_frame.winfo_width() - 60)
        cw = self.preview_font.measure("M") / max(0.01, self.preview_font.cget("size") / 11)

        def job():
            art = make_art()
            z = zoom
            if autofit:
                z = min(zoom, max(0.35, avail_w / max(1, art.width * cw)))
            img = None
            if want and art.width * art.height <= 30000:
                from ..export import render_image
                s = ExportSettings(font_size=max(5, int(round(14 * z))), padding=18, background=C["bg0"],
                                   foreground=C["text"], line_height=1.2)
                img = render_image(art, s)
            return {"art": art, "img": img, "zoom": z}
        return job

    def _image_opts(self) -> ImageOptions:
        tv = {k: v.get() for k, v in self.tvars.items()}
        def num(k, d, t=float):
            try:
                return t(tv.get(k, d))
            except (TypeError, ValueError):
                return d
        return ImageOptions(cols=num("cols", 100, int), mode=tv.get("mode", "ascii"), ramp=tv.get("ramp", "standard") or "standard",
                            brightness=num("brightness", 0.0), contrast=num("contrast", 1.0), gamma=max(0.2, min(5, num("gamma", 1.0))),
                            invert=bool(tv.get("invert")), dither=tv.get("dither", "none"), color=tv.get("color", "none"),
                            threshold=num("threshold", 0.5), aspect=num("aspect", 0.5))

    def _make_box(self, text, tv, fid, o, fx):
        kind = tv.get("kind")
        try:
            pad = max(0, min(10, int(tv.get("padding", 1))))
        except ValueError:
            pad = 1
        if kind == "Decorative text box":
            return Art.from_text(text_box(text, tv.get("style", "rounded"), pad, tv.get("align", "center"), tv.get("title", "")))
        art = self.engine.render(fid, text, o, fx)
        if kind == "Terminal banner":
            return Art.from_text(text_box(art.to_text(), tv.get("style", "rounded"), pad, tv.get("align", "center"), tv.get("title", "")))
        if kind == "GitHub README banner":
            return Art.from_text(to_markdown(art, tv.get("title", "")))
        return Art.from_text(to_code(art, tv.get("lang", "python"), "BANNER"))

    def _poll(self) -> None:
        try:
            while True:
                tag, gen, res, err, dt = self.results.get_nowait()
                if tag == "gallery":
                    self._gallery_result(gen, res, err)
                    continue
                if tag == "recommend":
                    self._show_recommend(res, err)
                    continue
                if gen != self.render_gen:
                    continue
                if err is not None:
                    self.status(f"Render error: {err}", "err")
                    continue
                self._show_art(res, dt)
        except queue.Empty:
            pass
        self.root.after(30, self._poll)

    def _color_tag(self, fg, bg) -> str:
        key = ((fg if fg is not None else -1) & 0xFFFFFFF, bg if bg is not None else -1)
        name = self._color_tags.get(key)
        if name is None:
            name = f"c{len(self._color_tags)}"
            self._color_tags[key] = name
            kw = {}
            if fg is not None:
                kw["foreground"] = rgb_to_hex(fg)
            if bg is not None:
                kw["background"] = rgb_to_hex(bg)
            self.preview.tag_configure(name, **kw)
            self.compare_text.tag_configure(name, **kw)
            self.tool_out.tag_configure(name, **kw)
        return name

    def _paint(self, widget: tk.Text, art: Art, clear: bool = True) -> None:
        widget.configure(state="normal")
        if clear:
            widget.delete("1.0", "end")
        if len(self._color_tags) > 6000:
            self._color_tags.clear()
            for w in (self.preview, self.compare_text, self.tool_out):
                for t in w.tag_names():
                    if t.startswith("c") and t[1:].isdigit():
                        w.tag_delete(t)
        q = (lambda c: c & 0xF8F8F8) if art.width * art.height > 40000 else (lambda c: c)
        for y in range(art.height):
            x = 0
            row = art.chars[y]
            while x < art.width:
                fg = art.fg[y][x]
                bg = art.bg[y][x]
                fgq = q(fg) if fg is not None else None
                bgq = q(bg) if bg is not None else None
                start = x
                while x < art.width and (q(art.fg[y][x]) if art.fg[y][x] is not None else None) == fgq and \
                        (q(art.bg[y][x]) if art.bg[y][x] is not None else None) == bgq:
                    x += 1
                seg = "".join(row[start:x])
                if fgq is None and bgq is None:
                    widget.insert("end", seg)
                else:
                    widget.insert("end", seg, self._color_tag(fgq, bgq))
            widget.insert("end", "\n")

    def _show_art(self, res, dt: float = 0.0) -> None:
        img = None
        if isinstance(res, dict):
            art, img, z = res["art"], res["img"], res["zoom"]
            self.preview_font.configure(size=max(4, int(round(11 * z))))
            self.zoom_var.set(f"{int(z * 100)}%")
        else:
            art = res
        self.current_art = art
        target = self.tool_out if self.mode in ("boxes", "encode") else self.preview
        if target is self.preview and img is not None:
            from PIL import ImageTk
            self._gimg = ImageTk.PhotoImage(img)
            self.gcanvas.delete("all")
            self.gcanvas.create_image(0, 0, image=self._gimg, anchor="nw")
            self.gcanvas.configure(scrollregion=(0, 0, img.width, img.height),
                                   yscrollcommand=self._preview_ys.set, xscrollcommand=self._preview_xs.set)
            tk.Misc.tkraise(self.gcanvas)
            self._preview_ys.configure(command=self.gcanvas.yview)
            self._preview_xs.configure(command=self.gcanvas.xview)
            self._paint(self.preview, art)
        else:
            self._paint(target, art)
            if target is self.preview:
                self.preview.tkraise()
                self._preview_ys.configure(command=self.preview.yview)
                self._preview_xs.configure(command=self.preview.xview)
        glow = art.meta.get("glow")
        self.preview.configure(bg=C["bg0"])
        w = width_warning(art.width) if self.mode == "text" else None
        name = self.fonts.entries[self.current_fid].name if self.mode == "text" else self.mode
        self.size_var.set(f"{art.width} × {art.height}  ·  {dt * 1000:.0f} ms" + ("  ·  glow on export" if glow else ""))
        if self.mode == "text":
            bad = self.engine.unsupported_chars(self.current_fid, self.get_text())
            if bad:
                self.status(f"{name}: cannot draw {' '.join(bad[:12])} — see Info › Smart recommendations for compatible fonts.", "warn")
            elif w:
                self.status(f"{name}: {w}", "warn")
            else:
                self.status(f"{name} · {len(self.filtered)} fonts in view", "info")
        self.update_info()

    # ------------------------------------------------------------- unicode
    def _render_unicode(self, text: str) -> None:
        self.uni_tree.delete(*self.uni_tree.get_children())
        line = text.replace("\n", " ")[:500]
        for key, name in STYLE_NAMES.items():
            try:
                self.uni_tree.insert("", "end", values=(name, stylize(line, key)))
            except ValueError:
                continue
        if contains_arabic(line):
            self.uni_tree.insert("", 0, values=("Arabic visual text (terminals)", visual_text(line)))
        self.current_art = Art.from_text("\n".join(f"{STYLE_NAMES[k]}: {stylize(line, k)}" for k in STYLE_NAMES))
        self.status("Double-click a row to copy it.")

    def _copy_unicode_row(self, _e=None) -> None:
        sel = self.uni_tree.selection()
        if sel:
            val = self.uni_tree.item(sel[0], "values")[1]
            self.root.clipboard_clear()
            self.root.clipboard_append(val)
            self.status("Copied: " + val[:60], "ok")

    def _render_encode(self, text: str) -> None:
        kind = self.tvars.get("enc").get() if self.tvars.get("enc") else "binary"
        dec = bool(self.tvars.get("decode").get()) if self.tvars.get("decode") else False
        try:
            out = decode(text, kind) if dec else encode(text, kind)
            level, msg = "info", f"{ENCODINGS[kind]} {'decoded' if dec else 'encoded'}"
        except ValueError as exc:
            out, level, msg = "", "err", f"Cannot {'decode' if dec else 'encode'}: {exc}"
        import textwrap
        wrapped = "\n".join(textwrap.fill(ln, 100, break_long_words=True) if len(ln) > 100 else ln for ln in out.split("\n"))
        art = Art.from_text(wrapped)
        self.current_art = art
        self._paint(self.tool_out, art)
        self.status(msg, level)

    # -------------------------------------------------------------- image
    def open_image(self) -> None:
        p = filedialog.askopenfilename(parent=self.root, title="Open image",
                                       filetypes=[("Images", "*.png *.jpg *.jpeg *.gif *.bmp *.webp *.ppm *.pgm"), ("All files", "*.*")])
        if not p:
            return
        try:
            if os.path.getsize(p) > 60 * 1024 * 1024:
                raise ValueError("image larger than 60 MB")
            with open(p, "rb") as fh:
                data = fh.read()
            try:
                self.image_data = load_image(data)
            except RuntimeError:
                self.image_data = self._load_image_tk(p)
            self.status(f"Loaded {os.path.basename(p)} ({self.image_data.width}×{self.image_data.height}) — processed locally", "ok")
            self.request_render()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Open image", f"Could not read image: {exc}", parent=self.root)

    def _load_image_tk(self, path: str) -> ImageData:
        ph = tk.PhotoImage(file=path)
        w, h = ph.width(), ph.height()
        step = max(1, int(max(w, h) / 600))
        if step > 1:
            ph = ph.subsample(step)
            w, h = ph.width(), ph.height()
        px = []
        for y in range(h):
            for x in range(w):
                r, g, b = ph.get(x, y)[:3]
                px.append((r << 16) | (g << 8) | b)
        return ImageData(w, h, px)

    # ------------------------------------------------------------- gallery
    GAL_HEAD = 22
    GAL_PAD = 14

    def start_gallery(self) -> None:
        self.gworker.gen += 1
        self.gallery_cache = {}
        self.gallery.delete("all")
        self.gallery_items = {}
        self.layout_gallery()

    def layout_gallery(self) -> None:
        """Compute item positions from metadata (no rendering) — supports hundreds of fonts."""
        if self.view != "gallery":
            return
        lh = self.gallery_font.metrics("linespace")
        y = 8
        self.gal_layout = []
        for fid in self.filtered:
            e = self.fonts.entries[fid]
            h = e.height
            if e.type == "raster":
                h = max(4, h // (4 if self.opts.raster_mode == "braille" else 2 if self.opts.raster_mode in ("half", "quarter") else 1))
            n = self.get_text().count("\n") + 1
            est = self.GAL_HEAD + min(60, h * n) * lh + self.GAL_PAD
            art = self.gallery_cache.get(fid)
            if isinstance(art, Art):
                est = self.GAL_HEAD + art.height * lh + self.GAL_PAD
            self.gal_layout.append((fid, y, est))
            y += est
        self.gallery.configure(scrollregion=(0, 0, max(1, self.gallery.winfo_width()), y + 20))
        self.paint_gallery()

    def _gallery_scroll(self, *args) -> None:
        self.gallery.yview(*args)
        self.paint_gallery()

    def paint_gallery(self) -> None:
        if self.view != "gallery" or not hasattr(self, "gal_layout"):
            return
        top = self.gallery.canvasy(0)
        bot = top + self.gallery.winfo_height()
        self.gallery.delete("item")
        text = self.get_text()[:200] or "LeerBox"
        o = copy.deepcopy(self.opts)
        fx = [e for e in copy.deepcopy(self.effects) if EFFECT_INFO.get(e["type"], ("text",))[0] == "text"]
        gen = self.gworker.gen
        lh = self.gallery_font.metrics("linespace")
        visible = 0
        for fid, y, h in self.gal_layout:
            if y + h < top - 400 or y > bot + 400:
                continue
            visible += 1
            e = self.fonts.entries[fid]
            sel = fid == self.current_fid
            self.gallery.create_rectangle(6, y, self.gallery.winfo_width() - 6, y + h - 6, fill=C["bg2"] if not sel else C["sel"],
                                          outline=C["line"], tags=("item", f"f::{fid}"))
            self.gallery.create_text(16, y + 11, text=f"{e.name}   ·   {e.category}   ·   h{e.height}", anchor="w",
                                     fill=C["muted"], font=(self.ui, 9), tags=("item", f"f::{fid}"))
            art = self.gallery_cache.get(fid)
            if art is None:
                self.gallery_cache[fid] = "pending"
                self.gworker.q.put((gen, fid, lambda fid=fid: self.engine.render(fid, text, o, fx)))
                self.gallery.create_text(16, y + self.GAL_HEAD + 4, text="rendering…", anchor="nw", fill=C["dim"],
                                         font=(self.ui, 9), tags=("item", f"f::{fid}"))
            elif isinstance(art, Art):
                self.gallery.create_text(16, y + self.GAL_HEAD, text=art.to_text(), anchor="nw", fill=C["text"],
                                         font=self.gallery_font, tags=("item", f"f::{fid}"))
            elif isinstance(art, Exception):
                self.gallery.create_text(16, y + self.GAL_HEAD + 4, text=f"error: {art}", anchor="nw", fill=C["err"],
                                         font=(self.ui, 9), tags=("item", f"f::{fid}"))
        self.status(f"Gallery: {len(self.gal_layout)} fonts · {visible} drawn (virtualized, background rendering)")

    def _gallery_result(self, gen, res, err) -> None:
        if gen != self.gworker.gen:
            return
        fid, art = res
        self.gallery_cache[fid] = art if err is None else err
        if not hasattr(self, "_gal_relayout") or not self._gal_relayout:
            self._gal_relayout = self.root.after(120, self._relayout_gallery)

    def _relayout_gallery(self) -> None:
        self._gal_relayout = None
        self.layout_gallery()

    def _gallery_click(self, e) -> None:
        item = self.gallery.find_closest(self.gallery.canvasx(e.x), self.gallery.canvasy(e.y))
        for t in self.gallery.gettags(item):
            if t.startswith("f::"):
                self.select_font(t[3:])
                return

    # ------------------------------------------------------------- compare
    def add_compare(self) -> None:
        if self.current_fid not in self.compare:
            self.compare.append(self.current_fid)
            del self.compare[:-6]
        self.status(f"Compare set: {len(self.compare)} font(s)", "ok")
        if self.view == "compare":
            self.render_compare()

    def clear_compare(self) -> None:
        self.compare = []
        self.render_compare()

    def render_compare(self) -> None:
        text = self.get_text() or "LeerBox"
        w = self.compare_text
        w.configure(state="normal")
        w.delete("1.0", "end")
        if not self.compare:
            w.insert("end", "No fonts in the compare set. Select a font and press “+ Compare”.")
            return
        self.compare_var.set(f"{len(self.compare)} fonts · same text, options and effects")
        for fid in self.compare:
            e = self.fonts.entries.get(fid)
            if not e:
                continue
            w.insert("end", f"── {e.name}  ({e.category}, {e.meta.get('source')})\n", ("hdr",))
            try:
                art = self.engine.render(fid, text, self.opts, self.effects)
                self._paint(w, art, clear=False)
                w.insert("end", f"   {art.width} cols × {art.height} rows\n\n", ("hdr",))
            except Exception as exc:  # noqa: BLE001
                w.insert("end", f"error: {exc}\n\n")
        w.tag_configure("hdr", foreground=C["muted"], font=(self.ui, 9))

    # ---------------------------------------------------------------- zoom
    def _zoom_size(self) -> int:
        return max(4, int(round(11 * self.zoom)))

    def set_zoom(self, z: float, manual: bool = True) -> None:
        if manual and hasattr(self, "autofit"):
            self.autofit.set(False)
        self.zoom = max(0.3, min(4.0, z))
        self.preview_font.configure(size=self._zoom_size())
        self.zoom_var.set(f"{int(self.zoom * 100)}%")
        self.settings.data["zoom"] = self.zoom
        if hasattr(self, "worker"):
            self.request_render(60)

    def fit_zoom(self) -> None:
        if not self.current_art:
            return
        cw = self.preview_font.measure("M") / self.zoom
        ch = self.preview_font.metrics("linespace") / self.zoom
        z = preview_scale(self.current_art.width, self.current_art.height, self.preview.winfo_width() - 40,
                          self.preview.winfo_height() - 30, cw, ch)
        self.set_zoom(z, manual=False)

    def fullscreen(self) -> None:
        if not self.current_art:
            return
        win = tk.Toplevel(self.root)
        win.configure(bg=C["bg0"])
        win.attributes("-fullscreen", True)
        f = tkfont.Font(family=self.mono, size=self._zoom_size())
        t = tk.Text(win, bg=C["bg0"], fg=C["text"], relief="flat", wrap="none", font=f, highlightthickness=0, padx=40, pady=30)
        t.pack(fill="both", expand=True)
        for name in self.preview.tag_names():
            cfg = {k: self.preview.tag_cget(name, k) for k in ("foreground", "background") if self.preview.tag_cget(name, k)}
            if cfg:
                t.tag_configure(name, **cfg)
        self._paint(t, self.current_art)
        art = self.current_art
        cw, chh = f.measure("M"), f.metrics("linespace")
        z = min((win.winfo_screenwidth() - 100) / max(1, art.width * cw), (win.winfo_screenheight() - 80) / max(1, art.height * chh))
        f.configure(size=max(4, int(f.cget("size") * min(z, 3))))
        t.configure(state="disabled")
        ttk.Label(win, text="Esc to close · Ctrl + / − to zoom", style="Bar.TLabel").place(relx=1.0, rely=1.0, anchor="se", x=-16, y=-10)
        win.bind("<Escape>", lambda e: win.destroy())
        win.bind("<Control-plus>", lambda e: f.configure(size=f.cget("size") + 1))
        win.bind("<Control-equal>", lambda e: f.configure(size=f.cget("size") + 1))
        win.bind("<Control-minus>", lambda e: f.configure(size=max(3, f.cget("size") - 1)))
        win.focus_set()

    # ---------------------------------------------------------------- info
    def update_info(self) -> None:
        e = self.fonts.entries.get(self.current_fid)
        if not e:
            return
        m = e.meta
        cov = m.get("coverage", {})
        lines = [
            f"{e.name}",
            f"Type: {m.get('format')} ({'genuine FIGlet/TOIlet font' if e.type in ('figlet', 'toilet') else 'raster typography (bitmap rasterized from a TTF)'})",
            f"Category: {m.get('category')}   Tags: {', '.join(m.get('tags', []))}",
            f"Height: {m.get('height')} rows   Layout bits: {m.get('layout')}   Direction: {'RTL' if m.get('direction') else 'LTR'}",
            f"Source: {m.get('source')}   {m.get('repo', '')}",
            f"Author: {m.get('author') or 'not stated in font file'}",
            f"License: {m.get('license')}  [{m.get('licenseTier')}]",
            f"Glyphs: {cov.get('glyphs', '?')}" + (f"   A–Z {cov.get('upper')}/26  a–z {cov.get('lower')}/26  digits {cov.get('digits')}/10" if 'upper' in cov else ""),
        ]
        if m.get("aliases"):
            lines.append(f"Duplicates merged: {len(m['aliases'])}")
        if self.current_art is not None and self.mode == "text":
            lines.append(f"Current output: {self.current_art.width} cols × {self.current_art.height} rows")
            bad = self.engine.unsupported_chars(self.current_fid, self.get_text())
            if bad:
                lines.append("Unsupported characters: " + " ".join(bad[:30]))
        self.info_text.configure(state="normal")
        self.info_text.delete("1.0", "end")
        self.info_text.insert("1.0", "\n".join(lines))
        self.info_text.configure(state="disabled")

    def run_recommend(self) -> None:
        text = self.get_text() or "LeerBox"
        target = self.rec_target.get()
        if contains_arabic(text):
            cands = [f for f, e in self.fonts.entries.items() if e.meta.get("category") == "Arabic"]
        else:
            cands = [f for f, e in self.fonts.entries.items() if e.type in ("figlet", "toilet")]
        self.status(f"Scoring {len(cands)} fonts for “{target}” (background)…")
        def job():
            return recommend(self.engine, text, target, cands, limit=25)
        def runner():
            try:
                res, err = job(), None
            except Exception as exc:  # noqa: BLE001
                res, err = None, exc
            self.results.put(("recommend", 0, res, err, 0))
        threading.Thread(target=runner, daemon=True).start()

    def _show_recommend(self, res, err) -> None:
        self.rec_tree.delete(*self.rec_tree.get_children())
        if err:
            self.status(f"Recommendation failed: {err}", "err")
            return
        for r in res:
            self.rec_tree.insert("", "end", iid=r["id"], values=(self.fonts.entries[r["id"]].name, f"{r['width']} × {r['height']}"))
        self.status(f"{len(res)} recommendations (deterministic scoring — see README)", "ok")

    def _rec_pick(self, _e=None) -> None:
        sel = self.rec_tree.selection()
        if sel:
            self.select_font(sel[0])

    # ------------------------------------------------------------ designs
    def _apply_design(self, fid: str, effects: list[dict]) -> None:
        self.effects = copy.deepcopy(effects)
        self._fx_refresh_list(0 if self.effects else None)
        self.select_font(fid if fid in self.fonts.entries else self.current_fid)

    def apply_curated(self) -> None:
        d = next((d for d in self.curated if d["name"] == self.curated_var.get()), None)
        if d:
            self._apply_design(d["font"], d["effects"])
            self.status(f"Applied curated design “{d['name']}”", "ok")

    def random_design(self) -> None:
        seed = random.randrange(1, 2 ** 31)
        d = random_design(self.fonts, seed)
        self._apply_design(d["font"], d["effects"])
        self.status(f"Random design (seed {seed}): {self.fonts.entries[d['font']].name}", "ok")

    def save_preset(self) -> None:
        from tkinter import simpledialog
        name = simpledialog.askstring("Save preset", "Preset name:", parent=self.root)
        if not name:
            return
        self.settings.data["presets"][name[:60]] = {"font": self.current_fid, "options": self.opts.to_dict(),
                                                    "effects": copy.deepcopy(self.effects), "export": self._read_export_settings().__dict__}
        self.settings.save()
        self.preset_cb.configure(values=sorted(self.settings.data["presets"]))
        self.status(f"Saved preset “{name}”", "ok")

    def load_preset(self) -> None:
        p = self.settings.data["presets"].get(self.preset_var.get())
        if not p:
            return
        from ..project import sanitize_effects
        self.opts = TextOptions.from_dict(p.get("options"))
        self._sync_option_vars()
        self._apply_design(p.get("font", self.current_fid), sanitize_effects(p.get("effects")))
        self.status(f"Loaded preset “{self.preset_var.get()}”", "ok")

    def delete_preset(self) -> None:
        n = self.preset_var.get()
        if n in self.settings.data["presets"]:
            del self.settings.data["presets"][n]
            self.settings.save()
            self.preset_cb.configure(values=sorted(self.settings.data["presets"]))
            self.preset_var.set("")

    def _sync_option_vars(self) -> None:
        for k, v in self.ovars.items():
            try:
                v.set(getattr(self.opts, k))
            except tk.TclError:
                pass

    # ------------------------------------------------------------- export
    def _art_for_export(self) -> Art | None:
        if self.current_art is None:
            messagebox.showinfo("Export", "Nothing to export yet.", parent=self.root)
            return None
        return self.current_art

    def export_dialog(self) -> None:
        art = self._art_for_export()
        if art is None:
            return
        fmt = self.fmt_var.get()
        label, ext = FORMATS[fmt]
        base = self.fonts.entries[self.current_fid].meta.get("name", "art") if self.mode == "text" else self.mode
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in base)
        p = filedialog.asksaveasfilename(parent=self.root, defaultextension=ext, initialfile=f"LeerBox_{safe}{ext}",
                                         filetypes=[(label, "*" + ext), ("All files", "*.*")])
        if not p:
            return
        s = self._read_export_settings()
        try:
            data = export_bytes(art, fmt, s)
            atomic_write(p, data)
            self.status(f"Exported {label}: {p} ({len(data):,} bytes)", "ok")
        except (OSError, ValueError, RuntimeError) as exc:
            messagebox.showerror("Export failed", str(exc), parent=self.root)

    def _clip(self, s: str, what: str) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(s)
        self.status(f"Copied {what} to clipboard", "ok")

    def copy_text(self) -> None:
        if self.current_art:
            self._clip(to_txt(self.current_art), "text")

    def copy_ansi(self) -> None:
        if self.current_art:
            self._clip(to_ansi(self.current_art, self._read_export_settings().ansi_mode), "ANSI text")

    def copy_md(self) -> None:
        if self.current_art:
            self._clip(to_markdown(self.current_art), "Markdown")

    def copy_html(self) -> None:
        if not self.current_art:
            return
        frag = to_html_fragment(self.current_art, self._read_export_settings())
        if copy_html_windows(frag, to_txt(self.current_art)):
            self.status("Copied as rich HTML (paste into Word, Outlook, Docs…)", "ok")
        else:
            self._clip(frag, "HTML source")

    def copy_code(self) -> None:
        if self.current_art:
            self._clip(to_code(self.current_art, self.code_var.get()), f"{CODE_LANGS[self.code_var.get()]} source")

    def batch_export(self) -> None:
        scope = self.batch_scope.get()
        ids = {"Favorites": [f for f in self.settings.data["favorites"] if f in self.fonts.entries],
               "Compare set": list(self.compare), "Current filter": list(self.filtered)}[scope]
        fmts = [f.strip().lower() for f in self.batch_fmts.get().split(",") if f.strip()]
        bad = [f for f in fmts if f not in FORMATS]
        if bad or not fmts:
            messagebox.showerror("Batch export", f"Unknown formats: {', '.join(bad) or '(none)'}\nValid: {', '.join(FORMATS)}", parent=self.root)
            return
        if not ids:
            messagebox.showinfo("Batch export", f"No fonts in “{scope}”.", parent=self.root)
            return
        if len(ids) * len(fmts) > 4000:
            messagebox.showerror("Batch export", "Too many files (limit 4000). Narrow the filter.", parent=self.root)
            return
        d = filedialog.askdirectory(parent=self.root, title="Choose output folder")
        if not d:
            return
        text, o, fx, s = self.get_text() or "LeerBox", copy.deepcopy(self.opts), copy.deepcopy(self.effects), self._read_export_settings()
        def run():
            ok, errs = 0, []
            manifest = []
            for i, fid in enumerate(ids):
                e = self.fonts.entries[fid]
                safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in e.meta.get("name", e.name))[:60]
                try:
                    art = self.engine.render(fid, text, o, fx)
                except Exception as exc:  # noqa: BLE001
                    errs.append(f"{e.name}: {exc}")
                    continue
                for f in fmts:
                    try:
                        path = os.path.join(d, f"{i + 1:03d}_{safe}{FORMATS[f][1]}")
                        atomic_write(path, export_bytes(art, f, s))
                        manifest.append({"font": e.name, "file": os.path.basename(path), "license": e.meta.get("license")})
                        ok += 1
                    except Exception as exc:  # noqa: BLE001
                        errs.append(f"{e.name} [{f}]: {exc}")
            atomic_write(os.path.join(d, "batch_manifest.json"), json.dumps({"text": text, "files": manifest, "errors": errs}, indent=1, ensure_ascii=False).encode("utf-8"))
            self.root.after(0, lambda: self.status(f"Batch export: {ok} files written to {d}" + (f", {len(errs)} errors (see batch_manifest.json)" if errs else ""), "warn" if errs else "ok"))
        threading.Thread(target=run, daemon=True).start()
        self.status(f"Batch exporting {len(ids)} fonts × {len(fmts)} formats in the background…")

    # ------------------------------------------------------------ projects
    def save_project(self) -> None:
        p = filedialog.asksaveasfilename(parent=self.root, defaultextension=".leerbox.json",
                                         filetypes=[("LeerBox project", "*.leerbox.json *.json")], initialfile="design.leerbox.json")
        if not p:
            return
        e = self.fonts.entries[self.current_fid]
        proj = make_project(self.get_text(), self.current_fid, e.name, self.opts, self.effects,
                            self._read_export_settings().__dict__, {"mode": self.mode})
        try:
            atomic_write(p, json.dumps(proj, indent=1, ensure_ascii=False).encode("utf-8"))
            self.status(f"Project saved: {p}", "ok")
        except OSError as exc:
            messagebox.showerror("Save project", str(exc), parent=self.root)

    def open_project(self) -> None:
        p = filedialog.askopenfilename(parent=self.root, filetypes=[("LeerBox project", "*.json"), ("All files", "*.*")])
        if not p:
            return
        try:
            if os.path.getsize(p) > 8 * 1024 * 1024:
                raise ValueError("project file too large")
            with open(p, "rb") as fh:
                proj = parse_project(fh.read())
        except (OSError, ValueError) as exc:
            messagebox.showerror("Open project", str(exc), parent=self.root)
            return
        self._load_project(proj)
        self.status(f"Opened project {os.path.basename(p)}", "ok")

    def _load_project(self, proj: dict) -> None:
        self.text_in.delete("1.0", "end")
        self.text_in.insert("1.0", proj["text"])
        self.opts = proj["options"]
        self._sync_option_vars()
        for k, v in proj.get("export", {}).items():
            if k in self.evars and v is not None:
                try:
                    self.evars[k].set(v)
                except tk.TclError:
                    pass
        fid = proj["font"]["id"]
        if fid not in self.fonts.entries:
            match = [f for f, e in self.fonts.entries.items() if e.name == proj["font"]["name"]]
            fid = match[0] if match else self.current_fid
            if not match:
                self.status(f"Font “{proj['font']['name']}” not available; kept current font.", "warn")
        self._apply_design(fid, proj["effects"])

    def _restore_state(self) -> None:
        last = self.settings.data.get("last") or {}
        try:
            if last:
                self._load_project(parse_project(json.dumps(last)))
        except ValueError:
            pass
        self.set_zoom(self.zoom, manual=False)
        self.set_scope("All")
        self.set_mode("text")
        self._fx_refresh_list()

    def _paste_image_shortcut(self, e=None):
        ws = self.workspaces.get("image") if getattr(self, "workspaces", None) else None
        if self.mode == "image" and ws is not None and not isinstance(self.root.focus_get(), (tk.Entry, ttk.Entry, tk.Text)):
            ws.paste_image()

    def on_close(self) -> None:
        try:
            e = self.fonts.entries[self.current_fid]
            self.settings.data["last"] = make_project(self.get_text(), self.current_fid, e.name, self.opts, self.effects,
                                                      self._read_export_settings().__dict__)
            self.settings.data["geometry"] = self.root.geometry()
            self.settings.save()
        finally:
            self.root.destroy()

    def about(self) -> None:
        st = self.fonts.stats()
        clear = sum(1 for e in self.fonts.entries.values() if e.type in ("figlet", "toilet") and e.meta.get("licenseTier") == "clear")
        arabic = sum(1 for e in self.fonts.entries.values() if e.meta.get("category") == "Arabic")
        messagebox.showinfo(
            "About",
            f"{APP_NAME} {APP_VERSION} — {APP_EDITION}\nLeerBox · local-first, offline, no telemetry\n\n"
            f"Genuine FIGlet/TOIlet fonts: {st['genuine']} ({clear} with explicit license terms)\n"
            f"Arabic raster fonts (OFL): {arabic}\nRaster typography designs: {st['raster'] - arabic}\n"
            f"Algorithmic Unicode styles: {len(STYLE_NAMES)}\nImported fonts: {st['imported']}\n\n"
            f"Pillow: {'available' if HAVE_PILLOW else 'not installed (PNG/BMP fallback renderer)'}\n"
            f"User data: {self.settings.dir}\n\nSee README.md, FONT_MANIFEST.json and THIRD_PARTY_LICENSES.txt.",
            parent=self.root)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:  # noqa: BLE001 - older Windows
            pass
    root = tk.Tk()
    try:
        StudioApp(root)
    except Exception as exc:  # noqa: BLE001
        LOG.exception("startup failed")
        messagebox.showerror("LeerBox Text Art Studio", f"Startup failed: {exc}")
        raise
    root.mainloop()


if __name__ == "__main__":
    main()
