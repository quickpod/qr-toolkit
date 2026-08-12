#!/usr/bin/env python3
r"""QR & Barcode Toolkit -- an Aura (QuickOpen design system) GUI on top of the
``qrkit`` API.

A single Aura window: sidebar sections for the four tools (QR code, Barcode,
Scan image, Batch from CSV) plus About.  Every operation calls the tested core
library (never re-implements QR/barcode logic) and runs on a background thread
so the UI stays responsive; the worker never touches tkinter -- it fills a
``queue.Queue`` that the main thread polls with ``self.after`` -- and results
land in the Aura status bar: an output path plus an "Open folder" button on
success, or the ``QRKitError`` message (never a traceback) on failure.
Generated and scanned images are previewed with Pillow's ``ImageTk``.

Design goals baked in here (mirrors the QuickOpen house style):
  * built on the vendored ``qrkit/aura.py`` design system, which layers the
    quickopen.ai look (deep space + light) over CustomTkinter.  Runtime deps:
    ``customtkinter`` (+ ``darkdetect``) -- declared in requirements.txt; the
    PyInstaller build adds ``--collect-all customtkinter``.
  * Importing this module does nothing.  Only :func:`main` builds a root
    window, and it degrades gracefully (prints a note, returns 0) with no
    display or with customtkinter missing.
  * Frozen-exe safe: bundled assets resolve via ``sys._MEIPASS`` / the exe dir
    when ``sys.frozen`` is set -- never ``__file__``.

100% AI-built, open source, published on QuickOpen (quickopen.ai).
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading

# tkinter/customtkinter/Pillow are imported lazily inside build_app()/main() so
# that merely importing this module (packaging, headless CI) never fails.

APP_NAME = "QR & Barcode Toolkit"
APP_VERSION = "1.0.0"
WINDOW_TITLE = "QR & Barcode Toolkit — by QuickOpen (quickopen.ai)"
PROJECT_URL = "https://quickopen.ai"
# UI-accent registry override (ui/aurakit/README.md §2): the app icon is
# near-black, unusable as a UI accent, so the registry assigns violet.
ACCENT = "#7c5cf0"

IMAGE_TYPES = [
    ("Images", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.gif"),
    ("All files", "*.*"),
]
PNG_TYPES = [("PNG image", "*.png"), ("All files", "*.*")]
SVG_TYPES = [("SVG image", "*.svg"), ("All files", "*.*")]
CSV_TYPES = [("CSV files", "*.csv"), ("All files", "*.*")]

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
# The app (built lazily; tkinter/customtkinter imported only inside build_app)
# ---------------------------------------------------------------------------
def build_app():
    """Construct and return the App class bound to live GUI imports."""
    import tkinter as tk
    from tkinter import filedialog, ttk
    import customtkinter as ctk

    from PIL import Image, ImageTk

    from . import aura, guiconfig
    from .barcode_gen import make_barcode, supported_kinds
    from .batch import batch_qr_from_csv
    from .errors import QRKitError
    from .qrgen import (
        make_qr, preset_email, preset_geo, preset_sms, preset_text,
        preset_url, preset_vcard, preset_wifi,
    )
    from .scan import scan_qr

    LABEL_W = 110       # px, the left field-label column

    # -- small reusable widgets ------------------------------------------
    class FileRow(ctk.CTkFrame):
        """A labelled path field + Browse button. ``mode`` picks the dialog."""

        def __init__(self, master, app, label, mode="open_image",
                     filetypes=None, on_change=None):
            super().__init__(master, fg_color="transparent")
            self.app = app
            self.mode = mode
            self.filetypes = filetypes
            self.var = tk.StringVar()
            ctk.CTkLabel(self, text=label, width=LABEL_W, anchor="w",
                         font=aura.font()).pack(side="left")
            ent = aura.AuraEntry(self, textvariable=self.var)
            ent.pack(side="left", fill="x", expand=True, padx=(0, 8))
            aura.AuraButton(self, "Browse…", kind="secondary", width=92,
                            command=self._browse).pack(side="left")
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
    class App(aura.AuraApp):
        def __init__(self):
            super().__init__(
                title=WINDOW_TITLE, app_name=APP_NAME, accent=ACCENT,
                theme=guiconfig.get_theme(),
                icon_png=asset_path("qr-toolkit.png"), version=APP_VERSION,
                tagline="offline codes",
                on_theme_change=guiconfig.set_theme,
                size=(1100, 700), min_size=(900, 560))

            self._busy = False
            self._previews = {}       # panel_id -> PhotoImage (keep alive)
            self._preview_labels = [] # raw tk preview labels, re-themed manually
            self._history = []
            self._last_output_dir = None
            self._tmpdir = tempfile.mkdtemp(prefix="qrtk_gui_")
            self._preview_files = {}  # panel_id -> last generated temp file

            # "Open folder" lives in the Aura status bar's action area and is
            # packed/unpacked exactly like the old result-bar button.
            self.openfolder_btn = aura.AuraButton(
                self.statusbar.actions, "Open folder", kind="secondary",
                height=30, command=self._open_last_folder)

            self._set_icon()
            self._build_menu()
            self.add_section("qr", "QR code", "▦", self._panel_qr)
            self.add_section("barcode", "Barcode", "▤", self._panel_barcode)
            self.add_section("scan", "Scan image", "⚲", self._panel_scan)
            self.add_section("batch", "Batch from CSV", "⛁", self._panel_batch)
            self.add_section("about", "About", "ℹ", self._panel_about)
            self.show("qr")
            self.protocol("WM_DELETE_WINDOW", self._on_close)

        # ---- assets / icon
        def _set_icon(self):
            try:
                ico = asset_path("qr-toolkit.ico")
                if ico and os.name == "nt":
                    self.iconbitmap(ico)
                    return
            except Exception:
                pass
            try:
                png = asset_path("qr-toolkit.png")
                if png:
                    img = tk.PhotoImage(file=png)
                    self._previews["_icon"] = img
                    self.iconphoto(True, img)
            except Exception:
                pass  # icon is cosmetic; never block launch

        # ---- navigation (Aura sections; keep the old tool-id entry points)
        def _select_tool(self, tool_id):
            self.show(tool_id)

        def show(self, sid):
            super().show(sid)
            # switching panels clears the previous result, like the old app
            if hasattr(self, "openfolder_btn"):
                self._clear_result()

        # ---- theme (Aura owns it; raw tk preview labels need a manual nudge)
        def set_theme(self, theme):
            super().set_theme(theme)
            self._retheme_previews()

        def _retheme_previews(self):
            for lbl in self._preview_labels:
                try:
                    lbl.configure(fg=aura.P("muted"))
                except Exception:
                    pass

        def _make_preview(self, parent, text, width=40, height=16):
            lbl = tk.Label(parent, text=text, bd=0, width=width, height=height,
                           bg=aura.P("surface"), fg=aura.P("muted"))
            aura.track(lbl, "canvas")       # bg follows the theme
            self._preview_labels.append(lbl)  # fg follows via _retheme_previews
            return lbl

        # ---- menu (native menus stay)
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
            viewm.add_command(
                label="Toggle dark mode",
                command=lambda: self.set_theme(
                    "light" if self.theme == "dark" else "dark"))
            bar.add_cascade(label="View", menu=viewm)

            helpm = tk.Menu(bar, tearoff=0)
            helpm.add_command(label="About", command=lambda: self.show("about"))
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
            self.show("scan")
            p = filedialog.askopenfilename(title="Open image", filetypes=IMAGE_TYPES)
            if p:
                self.load_path_scan(p)

        # ---- background operation runner
        # The worker thread must never touch tkinter (self.after from a
        # non-main thread raises "main thread is not in main loop" and would
        # leave _busy stuck forever).  It only fills a queue; the main thread
        # polls it with self.after.
        def _bg(self, work, on_ok, button=None, busy="Working…"):
            if self._busy:
                self._show_error("Please wait — an operation is already running.")
                return
            self._busy = True
            if button is not None:
                try:
                    button.state(["disabled"])
                except Exception:
                    pass
            self._clear_result(keep_status=True)
            self.set_status(busy, kind="working")

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
                    self._show_error(err)
                    return
                self.set_status("Done", kind="ok")
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

        # ---- status-bar helpers (errors go inline, never in a popup)
        def _clear_result(self, keep_status=False):
            self.openfolder_btn.pack_forget()
            if not keep_status:
                self.set_status("Ready")

        def _show_error(self, message):
            self.set_error(message)
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
                self.openfolder_btn.pack(side="left")
            self.set_success(message)

        def _open_last_folder(self):
            if self._last_output_dir:
                open_in_file_manager(self._last_output_dir)

        def _show_history(self):
            win = ctk.CTkToplevel(self)
            win.title("Session output history")
            win.geometry("640x380")
            aura.Caption(win, "Files produced in this session:").pack(
                anchor="w", padx=16, pady=(14, 6))
            frame = ctk.CTkFrame(win, fg_color="transparent")
            frame.pack(fill="both", expand=True, padx=16)
            lb = tk.Listbox(frame, activestyle="none")
            sb = ttk.Scrollbar(frame, orient="vertical", command=lb.yview)
            lb.configure(yscrollcommand=sb.set)
            sb.pack(side="right", fill="y")
            lb.pack(side="left", fill="both", expand=True)
            aura.track(lb, "listbox")
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

            btns = ctk.CTkFrame(win, fg_color="transparent")
            btns.pack(fill="x", padx=16, pady=12)
            aura.AuraButton(btns, "Open", kind="secondary",
                            command=lambda: _open_sel(False)).pack(side="left")
            aura.AuraButton(btns, "Open folder", kind="secondary",
                            command=lambda: _open_sel(True)).pack(
                side="left", padx=(8, 0))
            aura.AuraButton(btns, "Close", kind="ghost",
                            command=win.destroy).pack(side="right")
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
                self._previews[panel_id] = photo  # keep alive
                label.configure(image=photo, text="", width=photo.width(),
                                height=photo.height())
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
        # PANELS (Aura section builders; run lazily on first show)
        # =====================================================================
        def _suggest_out(self, stem, ext):
            return os.path.join(self._tmpdir, f"{stem}{ext}")

        @staticmethod
        def _labelled_row(parent, label, pady=3):
            row = ctk.CTkFrame(parent, fg_color="transparent")
            row.pack(fill="x", pady=pady)
            ctk.CTkLabel(row, text=label, width=LABEL_W, anchor="w",
                         font=aura.font()).pack(side="left")
            return row

        # ---------- Generate QR ----------
        def _panel_qr(self, parent):
            aura.Caption(parent, TOOL_DESCRIPTIONS["qr"]).pack(
                anchor="w", pady=(0, 12))
            cols = ctk.CTkFrame(parent, fg_color="transparent")
            cols.pack(fill="both", expand=True)
            right = ctk.CTkFrame(cols, fg_color="transparent")
            right.pack(side="right", fill="y", padx=(16, 0))
            left = ctk.CTkFrame(cols, fg_color="transparent")
            left.pack(side="left", fill="both", expand=True)

            # content preset + dynamic fields
            content = aura.Card(left, title="Content")
            content.pack(fill="x")
            row = self._labelled_row(content.body, "Preset", pady=(0, 6))
            self._qr_preset_var = tk.StringVar(value=QR_PRESETS[0][0])
            aura.AuraCombo(row, variable=self._qr_preset_var,
                           values=[lbl for lbl, _ in QR_PRESETS],
                           state="readonly", width=180,
                           command=lambda _v: self._qr_rebuild_fields()).pack(side="left")
            self._qr_fields_frame = ctk.CTkFrame(content.body,
                                                 fg_color="transparent")
            self._qr_fields_frame.pack(fill="x", pady=(4, 0))
            self._qr_field_vars = {}
            self._qr_field_widgets = {}

            # options: scale / border / error
            opts = aura.Card(left, title="Options")
            opts.pack(fill="x", pady=(14, 0))
            r1 = ctk.CTkFrame(opts.body, fg_color="transparent")
            r1.pack(fill="x", pady=2)
            ctk.CTkLabel(r1, text="Scale", width=60, anchor="w",
                         font=aura.font()).pack(side="left")
            self._qr_scale = tk.IntVar(value=8)
            ttk.Spinbox(r1, from_=1, to=40, width=5,
                        textvariable=self._qr_scale).pack(side="left")
            ctk.CTkLabel(r1, text="Border", width=60, anchor="w",
                         font=aura.font()).pack(side="left", padx=(16, 0))
            self._qr_border = tk.IntVar(value=4)
            ttk.Spinbox(r1, from_=0, to=20, width=5,
                        textvariable=self._qr_border).pack(side="left")
            r2 = ctk.CTkFrame(opts.body, fg_color="transparent")
            r2.pack(fill="x", pady=(8, 0))
            ctk.CTkLabel(r2, text="Error", width=60, anchor="w",
                         font=aura.font()).pack(side="left")
            self._qr_error_var = tk.StringVar(value=ERROR_LEVELS[1][0])
            aura.AuraCombo(r2, variable=self._qr_error_var, state="readonly",
                           width=180,
                           values=[lbl for lbl, _ in ERROR_LEVELS]).pack(side="left")

            # action buttons
            btns = ctk.CTkFrame(left, fg_color="transparent")
            btns.pack(fill="x", pady=(14, 0))
            self._qr_preview_btn = aura.AuraButton(btns, "Preview",
                                                   command=self._qr_preview)
            self._qr_preview_btn.pack(side="left")
            aura.AuraButton(btns, "Save PNG…", kind="secondary",
                            command=lambda: self._qr_save("png")).pack(
                side="left", padx=(8, 0))
            aura.AuraButton(btns, "Save SVG…", kind="secondary",
                            command=lambda: self._qr_save("svg")).pack(
                side="left", padx=(8, 0))
            aura.AuraButton(btns, "Copy image", kind="ghost",
                            command=self._qr_copy).pack(side="left", padx=(8, 0))

            # preview card on the right
            pv = aura.Card(right, title="Preview")
            pv.pack(fill="x")
            self._qr_preview_lbl = self._make_preview(pv.body,
                                                      "(no preview yet)",
                                                      width=40, height=18)
            self._qr_preview_lbl.pack(pady=4)

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
                row = self._labelled_row(self._qr_fields_frame, flabel)
                if kind == "check":
                    var = tk.BooleanVar(value=False)
                    ctk.CTkCheckBox(row, text="", width=24, variable=var,
                                    font=aura.font()).pack(side="left")
                    self._qr_field_vars[fkey] = var
                elif kind.startswith("combo:"):
                    values = kind.split(":", 1)[1].split(",")
                    var = tk.StringVar(value=values[0])
                    aura.AuraCombo(row, variable=var, values=values,
                                   state="readonly", width=180).pack(side="left")
                    self._qr_field_vars[fkey] = var
                elif kind == "text":
                    txt = tk.Text(row, height=3, width=20, wrap="word")
                    txt.pack(side="left", fill="x", expand=True)
                    aura.track(txt, "text")
                    self._qr_field_widgets[fkey] = txt
                elif kind == "password":
                    var = tk.StringVar()
                    aura.AuraEntry(row, textvariable=var, show="•").pack(
                        side="left", fill="x", expand=True)
                    self._qr_field_vars[fkey] = var
                else:
                    var = tk.StringVar()
                    aura.AuraEntry(row, textvariable=var).pack(
                        side="left", fill="x", expand=True)
                    self._qr_field_vars[fkey] = var

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
            aura.Caption(parent, TOOL_DESCRIPTIONS["barcode"]).pack(
                anchor="w", pady=(0, 12))
            cols = ctk.CTkFrame(parent, fg_color="transparent")
            cols.pack(fill="both", expand=True)
            right = ctk.CTkFrame(cols, fg_color="transparent")
            right.pack(side="right", fill="y", padx=(16, 0))
            left = ctk.CTkFrame(cols, fg_color="transparent")
            left.pack(side="left", fill="both", expand=True)

            card = aura.Card(left, title="Barcode")
            card.pack(fill="x")
            row = self._labelled_row(card.body, "Kind", pady=(0, 6))
            self._bc_kind = tk.StringVar(value=supported_kinds()[0])
            aura.AuraCombo(row, variable=self._bc_kind, state="readonly",
                           width=180, values=supported_kinds()).pack(side="left")
            row2 = self._labelled_row(card.body, "Data")
            self._bc_data = tk.StringVar()
            aura.AuraEntry(row2, textvariable=self._bc_data).pack(
                side="left", fill="x", expand=True)
            aura.Caption(card.body,
                         "EAN13 needs 12–13 digits, EAN8 7–8, UPCA 11–12 "
                         "(check digit auto-added). Code128/Code39 accept "
                         "text.", wraplength=440, justify="left").pack(
                anchor="w", pady=(6, 0))

            btns = ctk.CTkFrame(left, fg_color="transparent")
            btns.pack(fill="x", pady=(14, 0))
            self._bc_preview_btn = aura.AuraButton(btns, "Preview",
                                                   command=self._bc_preview)
            self._bc_preview_btn.pack(side="left")
            aura.AuraButton(btns, "Save PNG…", kind="secondary",
                            command=self._bc_save).pack(side="left", padx=(8, 0))
            aura.AuraButton(btns, "Copy image", kind="ghost",
                            command=self._bc_copy).pack(side="left", padx=(8, 0))

            pv = aura.Card(right, title="Preview")
            pv.pack(fill="x")
            self._bc_preview_lbl = self._make_preview(pv.body,
                                                      "(no preview yet)",
                                                      width=40, height=14)
            self._bc_preview_lbl.pack(pady=4)

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
            aura.Caption(parent, TOOL_DESCRIPTIONS["scan"]).pack(
                anchor="w", pady=(0, 12))
            self._scan_row = FileRow(parent, self, "Image", mode="open_image",
                                     filetypes=IMAGE_TYPES)
            self._scan_row.pack(fill="x")
            self._scan_btn = aura.AuraButton(parent, "Scan for QR codes",
                                             command=self._do_scan)
            self._scan_btn.pack(anchor="w", pady=(12, 12))

            split = ctk.CTkFrame(parent, fg_color="transparent")
            split.pack(fill="both", expand=True)
            right = ctk.CTkFrame(split, fg_color="transparent")
            right.pack(side="right", fill="y", padx=(16, 0))
            left = ctk.CTkFrame(split, fg_color="transparent")
            left.pack(side="left", fill="both", expand=True)

            results = aura.Card(left, title="Decoded results")
            results.pack(fill="both", expand=True)
            self._scan_out = tk.Text(results.body, height=12, width=20,
                                     wrap="word")
            self._scan_out.pack(fill="both", expand=True)
            aura.track(self._scan_out, "text")
            aura.AuraButton(results.body, "Copy results", kind="secondary",
                            command=self._scan_copy).pack(
                anchor="w", pady=(10, 0))

            pv = aura.Card(right, title="Image")
            pv.pack(fill="x")
            self._scan_preview_lbl = self._make_preview(pv.body,
                                                        "(open an image)",
                                                        width=34, height=14)
            self._scan_preview_lbl.pack(pady=4)

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
            aura.Caption(parent, TOOL_DESCRIPTIONS["batch"]).pack(
                anchor="w", pady=(0, 12))

            src = aura.Card(parent, title="Input")
            src.pack(fill="x")
            self._batch_csv = FileRow(src.body, self, "CSV file",
                                      mode="open_image", filetypes=CSV_TYPES)
            self._batch_csv.pack(fill="x", pady=(0, 6))
            row = self._labelled_row(src.body, "Data column")
            self._batch_col = tk.StringVar()
            aura.AuraEntry(row, textvariable=self._batch_col).pack(
                side="left", fill="x", expand=True)
            row2 = self._labelled_row(src.body, "Name column")
            self._batch_name_col = tk.StringVar()
            aura.AuraEntry(row2, textvariable=self._batch_name_col).pack(
                side="left", fill="x", expand=True)
            aura.Caption(src.body,
                         "Name column is optional — leave blank to name files "
                         "row1, row2, …").pack(anchor="w", pady=(6, 0))

            out = aura.Card(parent, title="Output")
            out.pack(fill="x", pady=(14, 0))
            self._batch_out = FileRow(out.body, self, "Output folder", mode="dir")
            self._batch_out.pack(fill="x", pady=(0, 8))
            r1 = ctk.CTkFrame(out.body, fg_color="transparent")
            r1.pack(fill="x", pady=2)
            ctk.CTkLabel(r1, text="Scale", width=60, anchor="w",
                         font=aura.font()).pack(side="left")
            self._batch_scale = tk.IntVar(value=8)
            ttk.Spinbox(r1, from_=1, to=40, width=5,
                        textvariable=self._batch_scale).pack(side="left")
            ctk.CTkLabel(r1, text="Border", width=60, anchor="w",
                         font=aura.font()).pack(side="left", padx=(16, 0))
            self._batch_border = tk.IntVar(value=4)
            ttk.Spinbox(r1, from_=0, to=20, width=5,
                        textvariable=self._batch_border).pack(side="left")
            ctk.CTkLabel(r1, text="Format", width=60, anchor="w",
                         font=aura.font()).pack(side="left", padx=(16, 0))
            self._batch_fmt = tk.StringVar(value="png")
            aura.AuraCombo(r1, variable=self._batch_fmt, state="readonly",
                           width=90, values=["png", "svg"]).pack(side="left")

            self._batch_btn = aura.AuraButton(parent, "Generate all",
                                              command=self._do_batch)
            self._batch_btn.pack(anchor="w", pady=(14, 0))

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

        # ---------- About ----------
        def _panel_about(self, parent):
            card = aura.Card(parent, title="About QR & Barcode Toolkit")
            card.pack(fill="x")
            aura.Heading(card.body, APP_NAME).pack(anchor="w")
            aura.Caption(card.body, f"Version {APP_VERSION}").pack(
                anchor="w", pady=(0, 10))
            ctk.CTkLabel(
                card.body, font=aura.font(), justify="left", anchor="w",
                wraplength=520,
                text="Generate QR codes (URL, Wi-Fi, vCard, email, SMS, geo, "
                     "text) and 1D barcodes, scan QR codes from images, and "
                     "batch-generate from a CSV.\n\n100% AI-built, open "
                     "source, published on QuickOpen. Fully offline.").pack(
                anchor="w")
            aura.Caption(card.body,
                         "Licensed under Apache-2.0. Built on: segno, "
                         "python-barcode, OpenCV, Pillow, CustomTkinter "
                         "(all MIT/BSD).").pack(anchor="w", pady=(10, 4))
            aura.AuraButton(card.body, "Project page: quickopen.ai",
                            kind="ghost",
                            command=lambda: open_with_default_app(
                                PROJECT_URL)).pack(anchor="w", pady=(6, 0))

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
    """Entry point: build the root window and run. Degrades on headless hosts.

    Importing this module does nothing; only this function creates a Tk root.
    With no display (e.g. a server), without Pillow, or without customtkinter
    installed, it prints a friendly note and returns 0 instead of raising.
    """
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
    except ImportError as exc:
        print(f"{APP_NAME}: the GUI needs the 'customtkinter' package "
              f"({exc}). Install it with:  pip install customtkinter")
        return 0
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
