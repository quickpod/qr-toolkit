#!/usr/bin/env python3
r"""QR & Barcode Toolkit -- a tkinter GUI on top of the ``qrkit`` API.

A single main window: a left sidebar (Generate QR, Barcode, Scan, Batch) and a
main panel that swaps to the selected tool.  Every operation calls the tested
core library (never re-implements QR/barcode logic) and runs on a background
thread so the UI stays responsive; results are marshalled back with
``self.after`` and shown in an inline result bar -- an output path plus an "Open
folder" button on success, or the ``QRKitError`` message (never a traceback) on
failure.  Generated and scanned images are previewed with Pillow's ``ImageTk``.

Design goals:
  * tkinter/ttk for the UI; Pillow only for image preview.  Dark mode is a
    ttk-style + palette swap.
  * Importing this module does nothing.  Only :func:`main` builds a root window,
    and it degrades gracefully (prints a note, returns 0) with no display.
  * Frozen-exe safe: bundled assets resolve via ``sys._MEIPASS`` / the exe dir
    when ``sys.frozen`` is set -- never ``__file__``.

100% AI-built, open source, published on QuickOpen (quickopen.ai).
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading

# tkinter/Pillow are imported lazily inside build_app()/main() so that merely
# importing this module (packaging, headless CI) never fails.

APP_NAME = "QR & Barcode Toolkit"
APP_VERSION = "1.0.0"
WINDOW_TITLE = "QR & Barcode Toolkit — by QuickOpen (quickopen.ai)"
PROJECT_URL = "https://quickopen.ai"

IMAGE_TYPES = [
    ("Images", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.gif"),
    ("All files", "*.*"),
]
PNG_TYPES = [("PNG image", "*.png"), ("All files", "*.*")]
SVG_TYPES = [("SVG image", "*.svg"), ("All files", "*.*")]
CSV_TYPES = [("CSV files", "*.csv"), ("All files", "*.*")]

# (category, [(tool_id, label), ...]) -- tool_id maps to a _panel_<id> method.
TOOL_TREE = [
    ("Generate", [
        ("qr", "QR code"),
        ("barcode", "Barcode"),
    ]),
    ("Decode", [
        ("scan", "Scan image"),
    ]),
    ("Batch", [
        ("batch", "Batch from CSV"),
    ]),
]

TOOL_DESCRIPTIONS = {
    "qr": "Pick a content preset, fill the fields, preview live, then save PNG/SVG.",
    "barcode": "Choose a symbology and data to render an EAN/UPC/Code128/Code39 PNG.",
    "scan": "Open an image and decode any QR codes in it with OpenCV.",
    "batch": "Generate one QR per row of a CSV column into an output folder.",
}

# QR content presets -> dynamic field spec: list of (key, label, kind).
# kind: "entry" | "password" | "check" | "combo:<a>,<b>,..." | "text"
QR_PRESETS = [
    ("URL", "url"),
    ("Wi-Fi", "wifi"),
    ("vCard", "vcard"),
    ("Email", "email"),
    ("SMS", "sms"),
    ("Geo", "geo"),
    ("Text", "text"),
]

QR_FIELDS = {
    "url": [("url", "URL", "entry")],
    "text": [("text", "Text", "text")],
    "wifi": [
        ("ssid", "Network (SSID)", "entry"),
        ("password", "Password", "password"),
        ("security", "Security", "combo:WPA,WEP,nopass"),
        ("hidden", "Hidden network", "check"),
    ],
    "vcard": [
        ("first_name", "First name", "entry"),
        ("last_name", "Last name", "entry"),
        ("org", "Organisation", "entry"),
        ("title", "Job title", "entry"),
        ("phone", "Phone", "entry"),
        ("email", "Email", "entry"),
        ("url", "Website", "entry"),
    ],
    "email": [
        ("to", "To", "entry"),
        ("subject", "Subject", "entry"),
        ("body", "Body", "text"),
    ],
    "sms": [
        ("number", "Phone number", "entry"),
        ("message", "Message", "text"),
    ],
    "geo": [
        ("lat", "Latitude", "entry"),
        ("lon", "Longitude", "entry"),
    ],
}

ERROR_LEVELS = [("Low (7%)", "l"), ("Medium (15%)", "m"),
                ("Quartile (25%)", "q"), ("High (30%)", "h")]

# ---- colour palettes (mirror the QuickOpen palette) -------------------------
PALETTES = {
    "light": {
        "bg": "#f5f7fa", "surface": "#ffffff", "text": "#141820",
        "muted": "#5b6472", "primary": "#2f5fe0", "primary_hi": "#2450c8",
        "entry": "#ffffff", "border": "#d5dae2", "sel": "#2f5fe0",
        "sel_fg": "#ffffff", "trough": "#e2e7ef", "ok": "#1f7a3d",
        "err": "#c0392b", "canvas": "#ffffff",
    },
    "dark": {
        "bg": "#0f1115", "surface": "#1a1e24", "text": "#f1f3f7",
        "muted": "#9aa4b2", "primary": "#5b86f7", "primary_hi": "#7098ff",
        "entry": "#1a1e24", "border": "#2a2f38", "sel": "#5b86f7",
        "sel_fg": "#0f1115", "trough": "#2a2f38", "ok": "#5bd68a",
        "err": "#ff6b5e", "canvas": "#222831",
    },
}


# ---------------------------------------------------------------------------
# Asset / frozen handling
# ---------------------------------------------------------------------------
def asset_path(name):
    """Locate a bundled asset from source OR a PyInstaller one-file build."""
    roots = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            roots.append(meipass)
        roots.append(os.path.dirname(os.path.abspath(sys.executable)))
    else:
        here = os.path.dirname(os.path.abspath(__file__))
        roots += [here, os.path.dirname(here), os.getcwd()]
    for root in roots:
        candidate = os.path.join(root, name)
        if os.path.exists(candidate):
            return candidate
    return None


def open_in_file_manager(path):
    """Best-effort 'reveal in file manager', guarded on every platform."""
    try:
        folder = path if os.path.isdir(path) else os.path.dirname(os.path.abspath(path))
        if hasattr(os, "startfile"):
            os.startfile(folder)  # noqa: S606 - intended (Windows)
        elif sys.platform == "darwin":
            import subprocess
            subprocess.Popen(["open", folder])
        else:
            import subprocess
            subprocess.Popen(["xdg-open", folder])
        return True
    except Exception:
        return False


def open_with_default_app(path):
    """Open a file/URL with the OS default application, guarded."""
    try:
        if hasattr(os, "startfile"):
            os.startfile(path)  # noqa: S606
        elif sys.platform == "darwin":
            import subprocess
            subprocess.Popen(["open", path])
        else:
            import subprocess
            subprocess.Popen(["xdg-open", path])
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# The app (built lazily; tkinter imported only inside build_app/main)
# ---------------------------------------------------------------------------
def build_app():
    """Construct and return the App class bound to a live tkinter import."""
    import tkinter as tk
    from tkinter import filedialog, ttk

    from PIL import Image, ImageTk

    from . import guiconfig
    from .barcode_gen import make_barcode, supported_kinds
    from .batch import batch_qr_from_csv
    from .errors import QRKitError
    from .qrgen import (
        make_qr, preset_email, preset_geo, preset_sms, preset_text,
        preset_url, preset_vcard, preset_wifi,
    )
    from .scan import scan_qr

    FONT = "Segoe UI"

    # -- small reusable widgets ------------------------------------------
    class FileRow(ttk.Frame):
        """A labelled path field + Browse button. ``mode`` picks the dialog."""

        def __init__(self, master, app, label, mode="open_image",
                     filetypes=None, on_change=None):
            super().__init__(master, style="TFrame")
            self.app = app
            self.mode = mode
            self.filetypes = filetypes
            self.var = tk.StringVar()
            ttk.Label(self, text=label, width=14, anchor="w").pack(side="left")
            ent = ttk.Entry(self, textvariable=self.var)
            ent.pack(side="left", fill="x", expand=True, padx=(0, 6))
            ttk.Button(self, text="Browse…", command=self._browse,
                       width=10).pack(side="left")
            if on_change:
                self.var.trace_add("write", lambda *_: on_change(self.var.get()))

        def _browse(self):
            ft = self.filetypes or IMAGE_TYPES
            if self.mode == "dir":
                p = filedialog.askdirectory(title="Choose a folder")
            elif self.mode == "save_png":
                p = filedialog.asksaveasfilename(
                    title="Save PNG", defaultextension=".png", filetypes=PNG_TYPES)
            elif self.mode == "save_svg":
                p = filedialog.asksaveasfilename(
                    title="Save SVG", defaultextension=".svg", filetypes=SVG_TYPES)
            else:
                p = filedialog.askopenfilename(title="Choose a file", filetypes=ft)
            if p:
                self.var.set(p)

        def get(self):
            return self.var.get().strip()

        def set(self, value):
            self.var.set(value or "")

    # -- the main window --------------------------------------------------
    class App(tk.Tk):
        def __init__(self):
            super().__init__()
            self.title(WINDOW_TITLE)
            self.geometry("1040x680")
            self.minsize(880, 560)

            self.theme = guiconfig.get_theme()
            self._busy = False
            self._panels = {}
            self._current = None
            self._tracked = []      # (tk_widget, role) for manual re-theming
            self._img_refs = {}     # panel_id -> PhotoImage (keep alive)
            self._history = []
            self._last_output_dir = None
            self._tmpdir = tempfile.mkdtemp(prefix="qrtk_gui_")
            self._preview_files = {}  # panel_id -> last generated temp file

            self._set_icon()
            self._build_menu()
            self._build_layout()
            self._apply_theme()
            self.protocol("WM_DELETE_WINDOW", self._on_close)
            self.after(50, self._select_first_tool)

        # ---- assets / icon
        def _set_icon(self):
            try:
                ico = asset_path("qr-toolkit.ico")
                if ico:
                    self.iconbitmap(ico)
                    return
            except Exception:
                pass
            try:
                png = asset_path("qr-toolkit.png")
                if png:
                    img = tk.PhotoImage(file=png)
                    self._img_refs["_icon"] = img
                    self.iconphoto(True, img)
            except Exception:
                pass  # icon is cosmetic; never block launch

        # ---- theming
        def track(self, widget, role):
            self._tracked.append((widget, role))

        def _pal(self):
            return PALETTES[self.theme]

        def _apply_theme(self):
            p = self._pal()
            style = ttk.Style(self)
            try:
                style.theme_use("clam")
            except Exception:
                pass
            self.configure(bg=p["bg"])
            style.configure(".", background=p["bg"], foreground=p["text"],
                            fieldbackground=p["entry"], bordercolor=p["border"],
                            font=(FONT, 10))
            style.configure("TFrame", background=p["bg"])
            style.configure("Sidebar.TFrame", background=p["surface"])
            style.configure("Card.TFrame", background=p["surface"])
            style.configure("TLabel", background=p["bg"], foreground=p["text"])
            style.configure("Muted.TLabel", background=p["bg"], foreground=p["muted"])
            style.configure("Header.TLabel", background=p["bg"], foreground=p["text"],
                            font=(FONT, 15, "bold"))
            style.configure("Sub.TLabel", background=p["bg"], foreground=p["muted"],
                            font=(FONT, 10))
            style.configure("Brand.TLabel", background=p["surface"],
                            foreground=p["text"], font=(FONT, 12, "bold"))
            style.configure("Ok.TLabel", background=p["bg"], foreground=p["ok"])
            style.configure("Err.TLabel", background=p["bg"], foreground=p["err"])
            style.configure("Status.TLabel", background=p["surface"],
                            foreground=p["muted"])
            style.configure("Preview.TLabel", background=p["canvas"],
                            foreground=p["muted"], anchor="center")
            style.configure("TButton", background=p["surface"], foreground=p["text"],
                            bordercolor=p["border"], focuscolor=p["surface"],
                            padding=(10, 5))
            style.map("TButton",
                      background=[("active", p["trough"]), ("disabled", p["bg"])],
                      foreground=[("disabled", p["muted"])])
            style.configure("Accent.TButton", background=p["primary"],
                            foreground="#ffffff", padding=(12, 6))
            style.map("Accent.TButton",
                      background=[("active", p["primary_hi"]),
                                  ("disabled", p["border"])],
                      foreground=[("disabled", p["muted"])])
            style.configure("Toggle.TButton", background=p["surface"],
                            foreground=p["text"], padding=(8, 4))
            for name in ("TEntry", "TSpinbox"):
                style.configure(name, fieldbackground=p["entry"], foreground=p["text"],
                                insertcolor=p["text"], bordercolor=p["border"])
            style.configure("TCombobox", fieldbackground=p["entry"],
                            foreground=p["text"], background=p["surface"],
                            arrowcolor=p["text"])
            style.map("TCombobox",
                      fieldbackground=[("readonly", p["entry"])],
                      foreground=[("readonly", p["text"])])
            style.configure("TCheckbutton", background=p["bg"], foreground=p["text"])
            style.map("TCheckbutton", background=[("active", p["bg"])])
            style.configure("TLabelframe", background=p["bg"], foreground=p["text"],
                            bordercolor=p["border"])
            style.configure("TLabelframe.Label", background=p["bg"],
                            foreground=p["muted"])
            style.configure("Sidebar.Treeview", background=p["surface"],
                            fieldbackground=p["surface"], foreground=p["text"],
                            bordercolor=p["border"], rowheight=26)
            style.map("Sidebar.Treeview", background=[("selected", p["primary"])],
                      foreground=[("selected", p["sel_fg"])])
            style.configure("TScrollbar", background=p["surface"],
                            troughcolor=p["bg"], bordercolor=p["border"],
                            arrowcolor=p["text"])
            style.configure("TSeparator", background=p["border"])

            for widget, role in list(self._tracked):
                try:
                    if role == "listbox":
                        widget.configure(bg=p["surface"], fg=p["text"],
                                         selectbackground=p["primary"],
                                         selectforeground=p["sel_fg"],
                                         highlightthickness=1,
                                         highlightbackground=p["border"], borderwidth=0)
                    elif role == "text":
                        widget.configure(bg=p["surface"], fg=p["text"],
                                         insertbackground=p["text"],
                                         selectbackground=p["primary"],
                                         selectforeground=p["sel_fg"],
                                         highlightthickness=1,
                                         highlightbackground=p["border"], borderwidth=0)
                    elif role == "preview":
                        widget.configure(bg=p["canvas"], highlightthickness=1,
                                         highlightbackground=p["border"])
                except Exception:
                    pass

        def toggle_theme(self):
            self.theme = "dark" if self.theme == "light" else "light"
            guiconfig.set_theme(self.theme)
            self._apply_theme()
            self._theme_btn.configure(
                text="☀ Light mode" if self.theme == "dark" else "🌙 Dark mode")

        # ---- menu
        def _build_menu(self):
            bar = tk.Menu(self)
            filem = tk.Menu(bar, tearoff=0)
            filem.add_command(label="Open image to scan…", accelerator="Ctrl+O",
                              command=self._open_scan)
            self._recent_menu = tk.Menu(filem, tearoff=0)
            filem.add_cascade(label="Open Recent", menu=self._recent_menu)
            self._fill_recent_menu()
            filem.add_separator()
            filem.add_command(label="Session output history…", command=self._show_history)
            filem.add_separator()
            filem.add_command(label="Exit", command=self._on_close)
            bar.add_cascade(label="File", menu=filem)

            viewm = tk.Menu(bar, tearoff=0)
            viewm.add_command(label="Toggle dark mode", command=self.toggle_theme)
            bar.add_cascade(label="View", menu=viewm)

            helpm = tk.Menu(bar, tearoff=0)
            helpm.add_command(label="About", command=self._about)
            helpm.add_command(label="Open project page (quickopen.ai)",
                              command=lambda: open_with_default_app(PROJECT_URL))
            bar.add_cascade(label="Help", menu=helpm)
            self.configure(menu=bar)
            self.bind_all("<Control-o>", lambda e: self._open_scan())

        def _fill_recent_menu(self):
            self._recent_menu.delete(0, "end")
            recent = guiconfig.get_recent()
            if not recent:
                self._recent_menu.add_command(label="(none)", state="disabled")
                return
            for path in recent:
                exists = os.path.exists(path)
                label = path if exists else path + "   (missing)"
                self._recent_menu.add_command(
                    label=label, state="normal" if exists else "disabled",
                    command=(lambda pp=path: open_with_default_app(pp)))
            self._recent_menu.add_separator()
            self._recent_menu.add_command(label="Clear list", command=self._clear_recent)

        def _clear_recent(self):
            guiconfig.clear_recent()
            self._fill_recent_menu()

        def _open_scan(self):
            self._select_tool("scan")
            p = filedialog.askopenfilename(title="Open image", filetypes=IMAGE_TYPES)
            if p and self._panels.get("scan") is not None:
                self.load_path_scan(p)

        # ---- layout
        def _build_layout(self):
            top = ttk.Frame(self, style="Sidebar.TFrame", padding=(12, 8))
            top.pack(fill="x", side="top")
            ttk.Label(top, text="QR & Barcode Toolkit",
                      style="Brand.TLabel").pack(side="left")
            ttk.Label(top, style="Status.TLabel",
                      text="  offline · open source · by QuickOpen").pack(side="left")
            self._theme_btn = ttk.Button(
                top, style="Toggle.TButton", command=self.toggle_theme,
                text="☀ Light mode" if self.theme == "dark" else "🌙 Dark mode")
            self._theme_btn.pack(side="right")

            body = ttk.Frame(self, style="TFrame")
            body.pack(fill="both", expand=True)

            side = ttk.Frame(body, style="Sidebar.TFrame", width=210)
            side.pack(side="left", fill="y")
            side.pack_propagate(False)
            self.nav = ttk.Treeview(side, show="tree", selectmode="browse",
                                    style="Sidebar.Treeview")
            self.nav.pack(fill="both", expand=True, padx=6, pady=6)
            self._nav_ids = {}
            for cat, tools in TOOL_TREE:
                cid = self.nav.insert("", "end", text=cat, open=True, tags=("cat",))
                for tid, label in tools:
                    iid = self.nav.insert(cid, "end", text="   " + label)
                    self._nav_ids[iid] = tid
            self.nav.tag_configure("cat", font=(FONT, 10, "bold"))
            self.nav.bind("<<TreeviewSelect>>", self._on_nav_select)

            main = ttk.Frame(body, style="TFrame", padding=(16, 12))
            main.pack(side="left", fill="both", expand=True)
            head = ttk.Frame(main, style="TFrame")
            head.pack(fill="x")
            self.title_lbl = ttk.Label(head, text="Welcome", style="Header.TLabel")
            self.title_lbl.pack(anchor="w")
            self.desc_lbl = ttk.Label(head, text="", style="Sub.TLabel",
                                      wraplength=720, justify="left")
            self.desc_lbl.pack(anchor="w", pady=(2, 8))
            ttk.Separator(main).pack(fill="x")
            self.container = ttk.Frame(main, style="TFrame")
            self.container.pack(fill="both", expand=True, pady=(10, 8))

            bar = ttk.Frame(self, style="Sidebar.TFrame", padding=(12, 6))
            bar.pack(fill="x", side="bottom")
            self.status_lbl = ttk.Label(bar, text="Ready", style="Status.TLabel",
                                        width=14, anchor="w")
            self.status_lbl.pack(side="left")
            self.openfolder_btn = ttk.Button(bar, text="Open folder",
                                             command=self._open_last_folder)
            self.result_lbl = ttk.Label(bar, text="", style="Status.TLabel",
                                        anchor="w", wraplength=700, justify="left")
            self.result_lbl.pack(side="left", fill="x", expand=True, padx=8)

        def _select_first_tool(self):
            for iid in self._nav_ids:
                self.nav.selection_set(iid)
                self.nav.see(iid)
                break

        def _select_tool(self, tool_id):
            for iid, tid in self._nav_ids.items():
                if tid == tool_id:
                    self.nav.selection_set(iid)
                    self.nav.see(iid)
                    return

        def _on_nav_select(self, _e=None):
            sel = self.nav.selection()
            if not sel:
                return
            tid = self._nav_ids.get(sel[0])
            if tid:
                self._show_tool(tid)

        def _show_tool(self, tool_id):
            if self._current is not None:
                self._current.pack_forget()
            panel = self._panels.get(tool_id)
            if panel is None:
                panel = ttk.Frame(self.container, style="TFrame")
                builder = getattr(self, "_panel_" + tool_id, None)
                if builder:
                    builder(panel)
                else:
                    ttk.Label(panel, text="Not implemented.").pack()
                self._panels[tool_id] = panel
                self._apply_theme()
            panel.pack(fill="both", expand=True)
            self._current = panel
            title, desc = self._tool_meta(tool_id)
            self.title_lbl.configure(text=title)
            self.desc_lbl.configure(text=desc)
            self._clear_result()

        def _tool_meta(self, tool_id):
            for _cat, tools in TOOL_TREE:
                for tid, label in tools:
                    if tid == tool_id:
                        return label, TOOL_DESCRIPTIONS.get(tid, "")
            return tool_id, ""

        # ---- background operation runner
        def _bg(self, work, on_ok, button=None, busy="Working…"):
            if self._busy:
                self._set_status("busy")
                self._show_error("Please wait — an operation is already running.")
                return
            self._busy = True
            if button is not None:
                try:
                    button.state(["disabled"])
                except Exception:
                    pass
            self._set_status(busy, kind="working")
            self._clear_result(keep_status=True)

            # The worker thread must never touch tkinter (self.after from a
            # non-main thread raises "main thread is not in main loop" and
            # would leave _busy stuck forever).  It only fills a queue; the
            # main thread polls it with self.after.
            import queue
            outcome = queue.Queue(maxsize=1)

            def run():
                try:
                    res, err = work(), None
                except QRKitError as ex:
                    res, err = None, str(ex)
                except Exception as ex:
                    res, err = None, f"Unexpected error: {ex}"
                outcome.put((res, err))

            def finish(res, err):
                self._busy = False
                if button is not None:
                    try:
                        button.state(["!disabled"])
                    except Exception:
                        pass
                if err is not None:
                    self._set_status("error", kind="err")
                    self._show_error(err)
                    return
                self._set_status("done", kind="ok")
                try:
                    on_ok(res)
                except Exception as ex:
                    self._show_error(f"Post-processing error: {ex}")

            def poll():
                try:
                    res, err = outcome.get_nowait()
                except queue.Empty:
                    self.after(50, poll)
                    return
                finish(res, err)

            threading.Thread(target=run, daemon=True).start()
            self.after(50, poll)

        # ---- result bar helpers
        def _set_status(self, text, kind="idle"):
            p = self._pal()
            color = {"working": p["primary"], "ok": p["ok"], "err": p["err"]}.get(
                kind, p["muted"])
            self.status_lbl.configure(text=text, foreground=color)

        def _clear_result(self, keep_status=False):
            self.result_lbl.configure(text="")
            self.openfolder_btn.pack_forget()
            if not keep_status:
                self._set_status("Ready")

        def _show_error(self, message):
            self.result_lbl.configure(text="✕ " + message, foreground=self._pal()["err"])
            self.openfolder_btn.pack_forget()

        def report_success(self, message, outputs=None):
            outputs = outputs or []
            for o in outputs:
                if o:
                    self._history.append(o)
                    guiconfig.add_recent(o)
            self._fill_recent_menu()
            if outputs:
                first = outputs[0]
                self._last_output_dir = (first if os.path.isdir(first)
                                         else os.path.dirname(os.path.abspath(first)))
                self.openfolder_btn.pack(side="right")
            self.result_lbl.configure(text="✓ " + message, foreground=self._pal()["ok"])
            self._set_status("done", kind="ok")

        def _open_last_folder(self):
            if self._last_output_dir:
                open_in_file_manager(self._last_output_dir)

        def _show_history(self):
            win = tk.Toplevel(self)
            win.title("Session output history")
            win.geometry("640x360")
            win.configure(bg=self._pal()["bg"])
            ttk.Label(win, style="Sub.TLabel", padding=10,
                      text="Files produced in this session:").pack(anchor="w")
            frame = ttk.Frame(win, style="TFrame")
            frame.pack(fill="both", expand=True, padx=10)
            lb = tk.Listbox(frame, activestyle="none")
            sb = ttk.Scrollbar(frame, orient="vertical", command=lb.yview)
            lb.configure(yscrollcommand=sb.set)
            sb.pack(side="right", fill="y")
            lb.pack(side="left", fill="both", expand=True)
            self.track(lb, "listbox")
            for o in self._history:
                lb.insert("end", o)
            if not self._history:
                lb.insert("end", "(nothing produced yet)")

            def _open_sel(reveal=False):
                sel = lb.curselection()
                if not sel:
                    return
                path = lb.get(sel[0])
                if os.path.exists(path):
                    (open_in_file_manager if reveal else open_with_default_app)(path)

            btns = ttk.Frame(win, style="TFrame", padding=10)
            btns.pack(fill="x")
            ttk.Button(btns, text="Open", command=lambda: _open_sel(False)).pack(side="left")
            ttk.Button(btns, text="Open folder",
                       command=lambda: _open_sel(True)).pack(side="left", padx=6)
            ttk.Button(btns, text="Close", command=win.destroy).pack(side="right")
            self._apply_theme()

        def _about(self):
            win = tk.Toplevel(self)
            win.title("About QR & Barcode Toolkit")
            win.configure(bg=self._pal()["bg"])
            win.resizable(False, False)
            frm = ttk.Frame(win, style="TFrame", padding=18)
            frm.pack(fill="both", expand=True)
            ttk.Label(frm, text="QR & Barcode Toolkit",
                      style="Header.TLabel").pack(anchor="w")
            ttk.Label(frm, text=f"Version {APP_VERSION}",
                      style="Sub.TLabel").pack(anchor="w", pady=(0, 8))
            ttk.Label(frm, style="TLabel", justify="left", wraplength=380,
                      text="Generate QR codes (URL, Wi-Fi, vCard, email, SMS, geo, "
                           "text) and 1D barcodes, scan QR codes from images, and "
                           "batch-generate from a CSV.\n\n100% AI-built, open source, "
                           "published on QuickOpen. Fully offline.").pack(anchor="w")
            ttk.Label(frm, style="Sub.TLabel", justify="left", wraplength=380,
                      text="Licensed under Apache-2.0. Built on: segno, "
                           "python-barcode, OpenCV, Pillow.").pack(anchor="w", pady=(8, 4))
            link = ttk.Label(frm, text="Project page: quickopen.ai",
                             style="Ok.TLabel", cursor="hand2")
            link.pack(anchor="w", pady=(4, 10))
            link.bind("<Button-1>", lambda e: open_with_default_app(PROJECT_URL))
            ttk.Button(frm, text="Close", command=win.destroy).pack(anchor="e")
            win.transient(self)
            try:
                win.grab_set()  # can raise "grab failed: window not viewable"
            except tk.TclError:
                pass

        # ---- image preview helper (Pillow -> ImageTk)
        def _show_preview(self, panel_id, label, path, max_side=340):
            try:
                im = Image.open(path)
                im = im.convert("RGBA") if im.mode == "P" else im
                im.thumbnail((max_side, max_side), Image.LANCZOS)
                photo = ImageTk.PhotoImage(im)
                self._img_refs[panel_id] = photo  # keep alive
                label.configure(image=photo, text="")
            except Exception as exc:
                label.configure(image="", text=f"(could not preview: {exc})")

        def _copy_image(self, path):
            """Best-effort copy: image to clipboard on Windows, else copy the path."""
            try:
                if sys.platform.startswith("win"):
                    import io
                    import win32clipboard  # type: ignore
                    im = Image.open(path).convert("RGB")
                    buf = io.BytesIO()
                    im.save(buf, "BMP")
                    data = buf.getvalue()[14:]  # strip BMP file header -> DIB
                    win32clipboard.OpenClipboard()
                    win32clipboard.EmptyClipboard()
                    win32clipboard.SetClipboardData(win32clipboard.CF_DIB, data)
                    win32clipboard.CloseClipboard()
                    self.report_success("Image copied to clipboard.")
                    return
            except Exception:
                pass
            # fallback: put the file path on the text clipboard
            try:
                self.clipboard_clear()
                self.clipboard_append(path)
                self.report_success(f"Copied file path to clipboard: {path}", [path])
            except Exception as exc:
                self._show_error(f"Could not copy: {exc}")

        # =====================================================================
        # PANELS
        # =====================================================================
        def _suggest_out(self, stem, ext):
            return os.path.join(self._tmpdir, f"{stem}{ext}")

        # ---------- Generate QR ----------
        def _panel_qr(self, parent):
            left = ttk.Frame(parent, style="TFrame")
            left.pack(side="left", fill="both", expand=True)
            right = ttk.Frame(parent, style="TFrame")
            right.pack(side="right", fill="y", padx=(14, 0))

            # preset chooser
            row = ttk.Frame(left, style="TFrame")
            row.pack(fill="x", pady=(0, 6))
            ttk.Label(row, text="Content", width=14, anchor="w").pack(side="left")
            self._qr_preset_var = tk.StringVar(value=QR_PRESETS[0][0])
            preset_cb = ttk.Combobox(row, state="readonly", width=16,
                                     textvariable=self._qr_preset_var,
                                     values=[lbl for lbl, _ in QR_PRESETS])
            preset_cb.pack(side="left")
            preset_cb.bind("<<ComboboxSelected>>", lambda e: self._qr_rebuild_fields())

            # dynamic fields
            self._qr_fields_frame = ttk.Frame(left, style="TFrame")
            self._qr_fields_frame.pack(fill="x", pady=4)
            self._qr_field_vars = {}
            self._qr_field_widgets = {}

            # options: scale / border / error
            opts = ttk.Labelframe(left, text="Options", style="TLabelframe",
                                  padding=(10, 6))
            opts.pack(fill="x", pady=(8, 6))
            r1 = ttk.Frame(opts, style="TFrame")
            r1.pack(fill="x", pady=2)
            ttk.Label(r1, text="Scale", width=8).pack(side="left")
            self._qr_scale = tk.IntVar(value=8)
            ttk.Spinbox(r1, from_=1, to=40, width=5,
                        textvariable=self._qr_scale).pack(side="left")
            ttk.Label(r1, text="Border", width=8).pack(side="left", padx=(12, 0))
            self._qr_border = tk.IntVar(value=4)
            ttk.Spinbox(r1, from_=0, to=20, width=5,
                        textvariable=self._qr_border).pack(side="left")
            r2 = ttk.Frame(opts, style="TFrame")
            r2.pack(fill="x", pady=2)
            ttk.Label(r2, text="Error", width=8).pack(side="left")
            self._qr_error_var = tk.StringVar(value=ERROR_LEVELS[1][0])
            ttk.Combobox(r2, state="readonly", width=16,
                         textvariable=self._qr_error_var,
                         values=[lbl for lbl, _ in ERROR_LEVELS]).pack(side="left")

            # action buttons
            btns = ttk.Frame(left, style="TFrame")
            btns.pack(fill="x", pady=(8, 0))
            self._qr_preview_btn = ttk.Button(btns, text="Preview",
                                              style="Accent.TButton",
                                              command=self._qr_preview)
            self._qr_preview_btn.pack(side="left")
            ttk.Button(btns, text="Save PNG…",
                       command=lambda: self._qr_save("png")).pack(side="left", padx=6)
            ttk.Button(btns, text="Save SVG…",
                       command=lambda: self._qr_save("svg")).pack(side="left")
            ttk.Button(btns, text="Copy image",
                       command=self._qr_copy).pack(side="left", padx=6)

            # preview label on the right
            ttk.Label(right, text="Preview", style="Sub.TLabel").pack(anchor="w")
            self._qr_preview_lbl = tk.Label(right, width=44, height=20,
                                            text="(no preview yet)")
            self._qr_preview_lbl.pack(pady=6)
            self.track(self._qr_preview_lbl, "preview")

            self._qr_rebuild_fields()

        def _qr_current_preset_key(self):
            label = self._qr_preset_var.get()
            for lbl, key in QR_PRESETS:
                if lbl == label:
                    return key
            return "text"

        def _qr_rebuild_fields(self):
            for w in self._qr_fields_frame.winfo_children():
                w.destroy()
            self._qr_field_vars = {}
            self._qr_field_widgets = {}
            key = self._qr_current_preset_key()
            for fkey, flabel, kind in QR_FIELDS.get(key, []):
                row = ttk.Frame(self._qr_fields_frame, style="TFrame")
                row.pack(fill="x", pady=2)
                ttk.Label(row, text=flabel, width=14, anchor="w").pack(side="left")
                if kind == "check":
                    var = tk.BooleanVar(value=False)
                    ttk.Checkbutton(row, variable=var).pack(side="left")
                    self._qr_field_vars[fkey] = var
                elif kind.startswith("combo:"):
                    values = kind.split(":", 1)[1].split(",")
                    var = tk.StringVar(value=values[0])
                    ttk.Combobox(row, state="readonly", width=16, values=values,
                                 textvariable=var).pack(side="left")
                    self._qr_field_vars[fkey] = var
                elif kind == "text":
                    txt = tk.Text(row, height=3, width=34, wrap="word")
                    txt.pack(side="left", fill="x", expand=True)
                    self.track(txt, "text")
                    self._qr_field_widgets[fkey] = txt
                elif kind == "password":
                    var = tk.StringVar()
                    ttk.Entry(row, textvariable=var, show="•").pack(
                        side="left", fill="x", expand=True)
                    self._qr_field_vars[fkey] = var
                else:
                    var = tk.StringVar()
                    ttk.Entry(row, textvariable=var).pack(
                        side="left", fill="x", expand=True)
                    self._qr_field_vars[fkey] = var
            self._apply_theme()

        def _qr_read_fields(self):
            data = {}
            for k, var in self._qr_field_vars.items():
                data[k] = var.get()
            for k, txt in self._qr_field_widgets.items():
                data[k] = txt.get("1.0", "end").rstrip("\n")
            return data

        def _qr_build_payload(self):
            key = self._qr_current_preset_key()
            f = self._qr_read_fields()
            if key == "url":
                return preset_url(f.get("url"))
            if key == "text":
                return preset_text(f.get("text", ""))
            if key == "wifi":
                return preset_wifi(f.get("ssid"), f.get("password"),
                                   security=f.get("security", "WPA"),
                                   hidden=bool(f.get("hidden")))
            if key == "email":
                return preset_email(f.get("to"), subject=f.get("subject", ""),
                                    body=f.get("body", ""))
            if key == "sms":
                return preset_sms(f.get("number"), message=f.get("message", ""))
            if key == "geo":
                return preset_geo(f.get("lat"), f.get("lon"))
            if key == "vcard":
                return preset_vcard(f)
            return preset_text("")

        def _int_var(self, var, what):
            """Read an IntVar backing a Spinbox; typed junk must not leak a
            TclError traceback -- surface it as the app error instead."""
            try:
                return int(var.get())
            except Exception:
                raise QRKitError(f"{what} must be a whole number.")

        def _qr_opts(self):
            err = "m"
            for lbl, code in ERROR_LEVELS:
                if lbl == self._qr_error_var.get():
                    err = code
            return dict(scale=self._int_var(self._qr_scale, "Scale"),
                        border=self._int_var(self._qr_border, "Border"),
                        error=err)

        def _qr_preview(self):
            try:
                payload = self._qr_build_payload()
                opts = self._qr_opts()
            except QRKitError as ex:
                self._show_error(str(ex))
                return
            out = self._suggest_out("qr_preview", ".png")

            def work():
                return make_qr(payload, out, fmt="png", **opts)

            def ok(path):
                self._preview_files["qr"] = path
                self._show_preview("qr", self._qr_preview_lbl, path)
                self.report_success("Preview updated.")

            self._bg(work, ok, button=self._qr_preview_btn, busy="Rendering…")

        def _qr_save(self, fmt):
            try:
                payload = self._qr_build_payload()
                opts = self._qr_opts()
            except QRKitError as ex:
                self._show_error(str(ex))
                return
            ftypes = SVG_TYPES if fmt == "svg" else PNG_TYPES
            dest = filedialog.asksaveasfilename(
                title=f"Save {fmt.upper()}", defaultextension="." + fmt,
                filetypes=ftypes)
            if not dest:
                return

            def work():
                return make_qr(payload, dest, fmt=fmt, **opts)

            def ok(path):
                if fmt == "png":
                    self._preview_files["qr"] = path
                    self._show_preview("qr", self._qr_preview_lbl, path)
                self.report_success(f"Saved QR → {path}", [path])

            self._bg(work, ok, busy="Saving…")

        def _qr_copy(self):
            path = self._preview_files.get("qr")
            if not path or not os.path.exists(path):
                self._show_error("Generate a preview first, then Copy image.")
                return
            self._copy_image(path)

        # ---------- Barcode ----------
        def _panel_barcode(self, parent):
            left = ttk.Frame(parent, style="TFrame")
            left.pack(side="left", fill="both", expand=True)
            right = ttk.Frame(parent, style="TFrame")
            right.pack(side="right", fill="y", padx=(14, 0))

            row = ttk.Frame(left, style="TFrame")
            row.pack(fill="x", pady=(0, 6))
            ttk.Label(row, text="Kind", width=14, anchor="w").pack(side="left")
            self._bc_kind = tk.StringVar(value=supported_kinds()[0])
            ttk.Combobox(row, state="readonly", width=16, textvariable=self._bc_kind,
                         values=supported_kinds()).pack(side="left")

            row2 = ttk.Frame(left, style="TFrame")
            row2.pack(fill="x", pady=4)
            ttk.Label(row2, text="Data", width=14, anchor="w").pack(side="left")
            self._bc_data = tk.StringVar()
            ttk.Entry(row2, textvariable=self._bc_data).pack(
                side="left", fill="x", expand=True)

            ttk.Label(left, style="Muted.TLabel", wraplength=420, justify="left",
                      text="EAN13 needs 12–13 digits, EAN8 7–8, UPCA 11–12 "
                           "(check digit auto-added). Code128/Code39 accept text.").pack(
                anchor="w", pady=(2, 8))

            btns = ttk.Frame(left, style="TFrame")
            btns.pack(fill="x", pady=(4, 0))
            self._bc_preview_btn = ttk.Button(btns, text="Preview",
                                              style="Accent.TButton",
                                              command=self._bc_preview)
            self._bc_preview_btn.pack(side="left")
            ttk.Button(btns, text="Save PNG…",
                       command=self._bc_save).pack(side="left", padx=6)
            ttk.Button(btns, text="Copy image",
                       command=self._bc_copy).pack(side="left")

            ttk.Label(right, text="Preview", style="Sub.TLabel").pack(anchor="w")
            self._bc_preview_lbl = tk.Label(right, width=44, height=16,
                                            text="(no preview yet)")
            self._bc_preview_lbl.pack(pady=6)
            self.track(self._bc_preview_lbl, "preview")

        def _bc_preview(self):
            data = self._bc_data.get().strip()
            kind = self._bc_kind.get()
            if not data:
                self._show_error("Enter the barcode data.")
                return
            out = self._suggest_out("barcode_preview", ".png")

            def work():
                return make_barcode(kind, data, out)

            def ok(path):
                self._preview_files["barcode"] = path
                self._show_preview("barcode", self._bc_preview_lbl, path, max_side=380)
                self.report_success("Preview updated.")

            self._bg(work, ok, button=self._bc_preview_btn, busy="Rendering…")

        def _bc_save(self):
            data = self._bc_data.get().strip()
            kind = self._bc_kind.get()
            if not data:
                self._show_error("Enter the barcode data.")
                return
            dest = filedialog.asksaveasfilename(
                title="Save PNG", defaultextension=".png", filetypes=PNG_TYPES)
            if not dest:
                return

            def work():
                return make_barcode(kind, data, dest)

            def ok(path):
                self._preview_files["barcode"] = path
                self._show_preview("barcode", self._bc_preview_lbl, path, max_side=380)
                self.report_success(f"Saved barcode → {path}", [path])

            self._bg(work, ok, busy="Saving…")

        def _bc_copy(self):
            path = self._preview_files.get("barcode")
            if not path or not os.path.exists(path):
                self._show_error("Generate a preview first, then Copy image.")
                return
            self._copy_image(path)

        # ---------- Scan ----------
        def _panel_scan(self, parent):
            top = ttk.Frame(parent, style="TFrame")
            top.pack(fill="x")
            self._scan_row = FileRow(top, self, "Image", mode="open_image",
                                     filetypes=IMAGE_TYPES)
            self._scan_row.pack(fill="x")
            self._scan_btn = ttk.Button(parent, text="Scan for QR codes",
                                        style="Accent.TButton", command=self._do_scan)
            self._scan_btn.pack(anchor="w", pady=8)

            split = ttk.Frame(parent, style="TFrame")
            split.pack(fill="both", expand=True)
            left = ttk.Frame(split, style="TFrame")
            left.pack(side="left", fill="both", expand=True)
            right = ttk.Frame(split, style="TFrame")
            right.pack(side="right", fill="y", padx=(14, 0))

            ttk.Label(left, text="Decoded results", style="Sub.TLabel").pack(anchor="w")
            self._scan_out = tk.Text(left, height=12, wrap="word")
            self._scan_out.pack(fill="both", expand=True, pady=6)
            self.track(self._scan_out, "text")
            ttk.Button(left, text="Copy results",
                       command=self._scan_copy).pack(anchor="w")

            ttk.Label(right, text="Image", style="Sub.TLabel").pack(anchor="w")
            self._scan_preview_lbl = tk.Label(right, width=36, height=16,
                                              text="(open an image)")
            self._scan_preview_lbl.pack(pady=6)
            self.track(self._scan_preview_lbl, "preview")

        def load_path_scan(self, path):
            self._scan_row.set(path)
            if os.path.exists(path):
                self._show_preview("scan", self._scan_preview_lbl, path, max_side=300)

        def _do_scan(self):
            path = self._scan_row.get()
            if not path:
                self._show_error("Choose an image to scan.")
                return
            self._show_preview("scan", self._scan_preview_lbl, path, max_side=300)
            guiconfig.add_recent(path)
            self._fill_recent_menu()

            def work():
                return scan_qr(path)

            def ok(results):
                self._scan_out.delete("1.0", "end")
                if not results:
                    self._scan_out.insert("end", "(no QR code found)")
                    self.report_success("Scan complete — no QR codes found.")
                    return
                for i, r in enumerate(results, 1):
                    self._scan_out.insert("end", f"[{i}] {r}\n")
                self.report_success(f"Decoded {len(results)} QR code(s).")

            self._bg(work, ok, button=self._scan_btn, busy="Scanning…")

        def _scan_copy(self):
            text = self._scan_out.get("1.0", "end").strip()
            if not text:
                self._show_error("Nothing to copy — scan an image first.")
                return
            try:
                self.clipboard_clear()
                self.clipboard_append(text)
                self.report_success("Results copied to clipboard.")
            except Exception as exc:
                self._show_error(f"Could not copy: {exc}")

        # ---------- Batch ----------
        def _panel_batch(self, parent):
            self._batch_csv = FileRow(parent, self, "CSV file", mode="open_image",
                                      filetypes=CSV_TYPES)
            self._batch_csv.pack(fill="x", pady=2)

            row = ttk.Frame(parent, style="TFrame")
            row.pack(fill="x", pady=2)
            ttk.Label(row, text="Data column", width=14, anchor="w").pack(side="left")
            self._batch_col = tk.StringVar()
            ttk.Entry(row, textvariable=self._batch_col).pack(
                side="left", fill="x", expand=True)

            row2 = ttk.Frame(parent, style="TFrame")
            row2.pack(fill="x", pady=2)
            ttk.Label(row2, text="Name column", width=14,
                      anchor="w").pack(side="left")
            self._batch_name_col = tk.StringVar()
            ttk.Entry(row2, textvariable=self._batch_name_col).pack(
                side="left", fill="x", expand=True)
            ttk.Label(parent, style="Muted.TLabel",
                      text="Name column is optional — leave blank to name files "
                           "row1, row2, …").pack(anchor="w", pady=(0, 6))

            self._batch_out = FileRow(parent, self, "Output folder", mode="dir")
            self._batch_out.pack(fill="x", pady=2)

            opts = ttk.Labelframe(parent, text="QR options", style="TLabelframe",
                                  padding=(10, 6))
            opts.pack(fill="x", pady=(8, 6))
            r1 = ttk.Frame(opts, style="TFrame")
            r1.pack(fill="x", pady=2)
            ttk.Label(r1, text="Scale", width=8).pack(side="left")
            self._batch_scale = tk.IntVar(value=8)
            ttk.Spinbox(r1, from_=1, to=40, width=5,
                        textvariable=self._batch_scale).pack(side="left")
            ttk.Label(r1, text="Border", width=8).pack(side="left", padx=(12, 0))
            self._batch_border = tk.IntVar(value=4)
            ttk.Spinbox(r1, from_=0, to=20, width=5,
                        textvariable=self._batch_border).pack(side="left")
            ttk.Label(r1, text="Format", width=8).pack(side="left", padx=(12, 0))
            self._batch_fmt = tk.StringVar(value="png")
            ttk.Combobox(r1, state="readonly", width=6, values=["png", "svg"],
                         textvariable=self._batch_fmt).pack(side="left")

            self._batch_btn = ttk.Button(parent, text="Generate all",
                                         style="Accent.TButton",
                                         command=self._do_batch)
            self._batch_btn.pack(anchor="w", pady=8)

        def _do_batch(self):
            csv_path = self._batch_csv.get()
            column = self._batch_col.get().strip()
            out_dir = self._batch_out.get()
            name_col = self._batch_name_col.get().strip() or None
            if not csv_path:
                self._show_error("Choose a CSV file.")
                return
            if not column:
                self._show_error("Enter the CSV data column name.")
                return
            if not out_dir:
                self._show_error("Choose an output folder.")
                return
            try:
                opts = dict(scale=self._int_var(self._batch_scale, "Scale"),
                            border=self._int_var(self._batch_border, "Border"),
                            fmt=self._batch_fmt.get())
            except QRKitError as ex:
                self._show_error(str(ex))
                return

            def work():
                return batch_qr_from_csv(csv_path, out_dir, column,
                                         name_column=name_col, **opts)

            def ok(outs):
                self.report_success(
                    f"Generated {len(outs)} QR code(s) in {out_dir}", [out_dir])

            self._bg(work, ok, button=self._batch_btn, busy="Generating…")

        # ---- close
        def _on_close(self):
            try:
                import shutil
                shutil.rmtree(self._tmpdir, ignore_errors=True)
            except Exception:
                pass
            self.destroy()

    return App


def main():
    """Entry point: build the root window and run. Degrades on headless hosts."""
    try:
        import tkinter as tk
    except Exception as exc:
        print(f"{APP_NAME}: a graphical environment with tkinter is required "
              f"to run the GUI ({exc}).")
        return 0

    try:
        from PIL import ImageTk  # noqa: F401  (fail early with a clear message)
    except Exception as exc:
        print(f"{APP_NAME}: Pillow (with ImageTk) is required for the GUI ({exc}).")
        return 0

    try:
        App = build_app()
        app = App()
    except tk.TclError as exc:
        print(f"{APP_NAME}: no graphical display available — cannot start the GUI "
              f"here ({exc}). This app is intended for the Windows desktop.")
        return 0
    except Exception as exc:
        print(f"{APP_NAME}: could not start the GUI ({exc}).")
        return 1

    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
