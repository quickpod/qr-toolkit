"""GUI regression tests (headless-safe: skipped when no display is available).

Covers the bugs that only show up when driving the real tkinter app:

* the background runner must marshal results back to the main thread without
  calling tkinter from the worker thread (and must never leave the app stuck
  in the busy state), and
* junk typed into the Scale/Border spinboxes must surface as the inline app
  error, not leak a raw TclError traceback.

Each test builds the app off-screen, drives it with synthetic input, and pumps
``update()`` instead of entering ``mainloop``.
"""

import os
import time

import pytest


def _new_app(monkeypatch, tmp_path):
    """Build the App with config redirected to a temp dir; skip if headless."""
    tkinter = pytest.importorskip("tkinter")
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("LOCALAPPDATA", str(home))

    from qrkit import gui

    App = gui.build_app()
    try:
        app = App()
    except tkinter.TclError as exc:  # no $DISPLAY / no window server
        pytest.skip(f"no graphical display available: {exc}")
    app.update()

    # record inline errors instead of painting them
    app.test_errors = []
    monkeypatch.setattr(
        type(app), "_show_error",
        lambda self, message: self.test_errors.append(message))
    return app


def _pump_until_idle(app, timeout=15.0):
    """Process events until the background operation finishes."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.update()
        if not app._busy:
            for _ in range(20):  # let queued after() callbacks drain
                app.update()
            if not app._busy:
                return
        time.sleep(0.01)
    raise AssertionError("GUI still busy after timeout")


@pytest.fixture
def app(monkeypatch, tmp_path):
    a = _new_app(monkeypatch, tmp_path)
    yield a
    try:
        a._on_close()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Bug: _bg used self.after() from the worker thread -> "main thread is not in
# main loop" + the app stuck busy forever.  The runner must complete purely
# via main-thread polling, and back-to-back operations must work.
# ---------------------------------------------------------------------------
def test_bg_preview_completes_and_app_not_stuck_busy(app):
    app._select_tool("qr")
    app.update()
    app._qr_preset_var.set("Text")
    app._qr_rebuild_fields()
    app._qr_field_widgets["text"].insert("1.0", "hello from the test")
    app._qr_preview()
    _pump_until_idle(app)

    assert app.test_errors == []
    path = app._preview_files.get("qr")
    assert path and os.path.exists(path)

    # a second operation must run too (busy flag must have been released)
    app._select_tool("barcode")
    app.update()
    app._bc_kind.set("Code128")
    app._bc_data.set("SECOND-OP")
    app._bc_preview()
    _pump_until_idle(app)
    assert app.test_errors == []
    path2 = app._preview_files.get("barcode")
    assert path2 and os.path.exists(path2)


def test_bg_reports_qrkit_error_from_worker(app):
    # invalid EAN13 data fails inside the worker; it must come back as the
    # inline app error and release the busy flag -- no traceback, no lockup.
    app._select_tool("barcode")
    app.update()
    app._bc_kind.set("EAN13")
    app._bc_data.set("not-digits")
    app._bc_preview()
    _pump_until_idle(app)
    assert len(app.test_errors) == 1
    assert "EAN" in app.test_errors[0] or "Invalid data" in app.test_errors[0]
    assert not app._busy


# ---------------------------------------------------------------------------
# Bug: junk in the Scale/Border spinboxes raised TclError out of the button
# callback instead of the app's inline error.
# ---------------------------------------------------------------------------
def test_qr_preview_junk_scale_shows_app_error(app):
    app._select_tool("qr")
    app.update()
    app._qr_preset_var.set("Text")
    app._qr_rebuild_fields()
    app._qr_field_widgets["text"].insert("1.0", "data")
    app._qr_scale.set("abc")  # what typing junk into the spinbox produces
    app._qr_preview()  # must not raise
    app.update()
    assert app.test_errors and "Scale" in app.test_errors[0]
    assert not app._busy


def test_qr_save_junk_border_shows_app_error(app, monkeypatch):
    from tkinter import filedialog
    monkeypatch.setattr(filedialog, "asksaveasfilename",
                        lambda **kw: pytest.fail("dialog must not open"))
    app._select_tool("qr")
    app.update()
    app._qr_preset_var.set("Text")
    app._qr_rebuild_fields()
    app._qr_field_widgets["text"].insert("1.0", "data")
    app._qr_border.set("nope")
    app._qr_save("png")  # must not raise and must not reach the dialog
    assert app.test_errors and "Border" in app.test_errors[0]


def test_batch_junk_scale_shows_app_error(app, tmp_path):
    csv_path = tmp_path / "in.csv"
    csv_path.write_text("name,link\na,https://a.example\n", encoding="utf-8")
    app._select_tool("batch")
    app.update()
    app._batch_csv.set(str(csv_path))
    app._batch_col.set("link")
    app._batch_out.set(str(tmp_path / "out"))
    app._batch_scale.set("junk")
    app._do_batch()  # must not raise
    app.update()
    assert app.test_errors and "Scale" in app.test_errors[0]
    assert not app._busy


# ---------------------------------------------------------------------------
# End-to-end through the GUI: batch runs in the background and produces files.
# ---------------------------------------------------------------------------
def test_batch_end_to_end_via_gui(app, tmp_path):
    csv_path = tmp_path / "in.csv"
    csv_path.write_text(
        "name,link\nalpha,https://a.example\nbeta,https://b.example\n",
        encoding="utf-8")
    out_dir = tmp_path / "out"
    app._select_tool("batch")
    app.update()
    app._batch_csv.set(str(csv_path))
    app._batch_col.set("link")
    app._batch_name_col.set("name")
    app._batch_out.set(str(out_dir))
    app._do_batch()
    _pump_until_idle(app)
    assert app.test_errors == []
    assert sorted(os.listdir(out_dir)) == ["alpha.png", "beta.png"]
