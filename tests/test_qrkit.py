"""Tests for qrkit: QR gen + scan round-trip, presets, barcodes, batch.

Deterministic and headless-friendly (no GUI import here).  The round-trip test
proves gen+scan end to end: a QR is written to a temp PNG, then decoded back
with the same OpenCV path the app uses.
"""

import csv
import os
import struct

import pytest

from qrkit import (
    QRKitError,
    batch_qr_from_csv,
    make_barcode,
    make_qr,
    preset_url,
    preset_vcard,
    preset_wifi,
    scan_qr,
)


def _is_png(path):
    with open(path, "rb") as fh:
        sig = fh.read(8)
    return sig == b"\x89PNG\r\n\x1a\n"


def _png_size(path):
    with open(path, "rb") as fh:
        head = fh.read(24)
    # IHDR width/height are big-endian uint32 at offset 16
    w, h = struct.unpack(">II", head[16:24])
    return w, h


# ---- make_qr writes a valid PNG -------------------------------------------
def test_make_qr_writes_valid_png(tmp_path):
    out = tmp_path / "q.png"
    result = make_qr("hello world", str(out), scale=6, border=4)
    assert result == str(out)
    assert out.exists()
    assert _is_png(str(out))
    w, h = _png_size(str(out))
    assert w > 0 and h > 0 and w == h  # QR codes are square


def test_make_qr_writes_svg(tmp_path):
    out = tmp_path / "q.svg"
    make_qr("https://quickopen.ai", str(out))
    assert out.exists()
    assert "<svg" in out.read_text(encoding="utf-8")[:400].lower()


def test_make_qr_rejects_empty(tmp_path):
    with pytest.raises(QRKitError):
        make_qr("", str(tmp_path / "x.png"))


def test_make_qr_rejects_bad_error(tmp_path):
    with pytest.raises(QRKitError):
        make_qr("data", str(tmp_path / "x.png"), error="z")


# ---- gen -> scan round-trip (the headline end-to-end test) ----------------
@pytest.mark.parametrize("payload", [
    "hello world",
    "https://quickopen.ai/projects/qr-toolkit",
    "WIFI:T:WPA;S:MyNet;P:s3cret;;",
])
def test_qr_roundtrip_scan(tmp_path, payload):
    out = tmp_path / "rt.png"
    # high error correction + generous scale => reliable decode
    make_qr(payload, str(out), scale=10, border=4, error="h")
    decoded = scan_qr(str(out))
    assert payload in decoded


def test_scan_missing_image_raises(tmp_path):
    with pytest.raises(QRKitError):
        scan_qr(str(tmp_path / "nope.png"))


def test_scan_no_qr_returns_empty(tmp_path):
    # a plain white PNG has no QR -> empty list, no error
    from PIL import Image
    blank = tmp_path / "blank.png"
    Image.new("RGB", (200, 200), "white").save(str(blank))
    assert scan_qr(str(blank)) == []


# ---- preset payload prefixes ----------------------------------------------
def test_preset_url_prefix():
    assert preset_url("https://example.com/path") == "https://example.com/path"
    # bare host gets an https scheme
    assert preset_url("example.com").startswith("https://")


def test_preset_wifi_prefix():
    payload = preset_wifi("MyNet", "p@ss", security="WPA")
    assert payload.startswith("WIFI:")
    assert "S:MyNet" in payload
    assert "P:p@ss" in payload


def test_preset_wifi_nopass_omits_password():
    payload = preset_wifi("Guest", "ignored", security="nopass")
    assert payload.startswith("WIFI:")
    assert "P:" not in payload


def test_preset_vcard_prefix():
    payload = preset_vcard({"first_name": "Ada", "last_name": "Lovelace",
                            "email": "ada@example.com"})
    assert payload.startswith("BEGIN:VCARD")
    assert "END:VCARD" in payload
    assert "FN:Ada Lovelace" in payload


def test_preset_vcard_requires_something():
    with pytest.raises(QRKitError):
        preset_vcard({})


# ---- barcodes --------------------------------------------------------------
def test_make_barcode_code128(tmp_path):
    out = tmp_path / "code128.png"
    path = make_barcode("Code128", "ABC-12345", str(out))
    assert os.path.exists(path)
    assert path.endswith(".png")
    assert _is_png(path)


def test_make_barcode_ean13(tmp_path):
    out = tmp_path / "ean13.png"
    # 12 digits; python-barcode computes the 13th check digit
    path = make_barcode("EAN13", "590123412345", str(out))
    assert os.path.exists(path)
    assert _is_png(path)


def test_make_barcode_bad_kind(tmp_path):
    with pytest.raises(QRKitError):
        make_barcode("QRCODE", "data", str(tmp_path / "x.png"))


def test_make_barcode_bad_data(tmp_path):
    # EAN13 requires digits; letters must fail cleanly as QRKitError
    with pytest.raises(QRKitError):
        make_barcode("EAN13", "not-a-number", str(tmp_path / "x.png"))


# ---- batch -----------------------------------------------------------------
def _write_csv(path, rows, header=("name", "link")):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)


def test_batch_produces_right_number_of_files(tmp_path):
    csv_path = tmp_path / "in.csv"
    out_dir = tmp_path / "out"
    _write_csv(csv_path, [
        ("alpha", "https://a.example"),
        ("beta", "https://b.example"),
        ("gamma", "https://c.example"),
    ])
    outs = batch_qr_from_csv(str(csv_path), str(out_dir), column="link",
                             name_column="name")
    assert len(outs) == 3
    assert all(os.path.exists(o) for o in outs)
    # deterministic names from the name column
    assert os.path.basename(outs[0]) == "alpha.png"
    # produced files are valid PNGs and round-trip
    assert scan_qr(outs[0]) == ["https://a.example"] or \
        "https://a.example" in scan_qr(outs[0])


def test_batch_default_names_and_blank_skip(tmp_path):
    csv_path = tmp_path / "in.csv"
    out_dir = tmp_path / "out"
    _write_csv(csv_path, [
        ("one", "https://one.example"),
        ("two", ""),  # blank -> skipped
        ("three", "https://three.example"),
    ])
    outs = batch_qr_from_csv(str(csv_path), str(out_dir), column="link")
    assert len(outs) == 2
    names = sorted(os.path.basename(o) for o in outs)
    assert names == ["row1.png", "row3.png"]


def test_batch_bad_column_raises(tmp_path):
    csv_path = tmp_path / "in.csv"
    _write_csv(csv_path, [("a", "x")])
    with pytest.raises(QRKitError):
        batch_qr_from_csv(str(csv_path), str(tmp_path / "o"), column="missing")
