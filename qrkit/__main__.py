"""Command-line interface: ``python -m qrkit <command> ...``.

Commands:
  qr       generate a QR code (with content presets)
  barcode  generate a 1D barcode
  scan     decode QR codes from an image
  batch    generate many QRs from a CSV

Any :class:`QRKitError` is reported to stderr and exits non-zero (2); other
unexpected failures exit 3.
"""

from __future__ import annotations

import argparse
import sys

from .barcode_gen import make_barcode, supported_kinds
from .batch import batch_qr_from_csv
from .errors import QRKitError
from .qrgen import (
    make_qr,
    preset_email,
    preset_geo,
    preset_sms,
    preset_text,
    preset_url,
    preset_vcard,
    preset_wifi,
)
from .scan import scan_qr

PRESETS = ("url", "wifi", "vcard", "email", "sms", "geo", "text")


def _payload_from_args(a):
    """Build the QR payload string from the chosen ``--preset`` and its fields."""
    preset = a.preset
    if preset == "url":
        return preset_url(a.data or a.url)
    if preset == "text":
        return preset_text(a.data or a.text or "")
    if preset == "wifi":
        return preset_wifi(a.ssid, a.password, security=a.security, hidden=a.hidden)
    if preset == "email":
        return preset_email(a.to, subject=a.subject, body=a.body)
    if preset == "sms":
        return preset_sms(a.number, message=a.message)
    if preset == "geo":
        return preset_geo(a.lat, a.lon)
    if preset == "vcard":
        fields = {
            "name": a.name, "first_name": a.first_name, "last_name": a.last_name,
            "org": a.org, "title": a.title, "phone": a.phone, "email": a.email,
            "url": a.vurl,
        }
        return preset_vcard(fields)
    # no preset: raw data
    return preset_text(a.data or "")


def cmd_qr(a):
    payload = _payload_from_args(a)
    out = make_qr(payload, a.output, scale=a.scale, border=a.border,
                  error=a.error, fmt=a.format)
    print(f"Wrote QR ({a.preset or 'raw'}) -> {out}")


def cmd_barcode(a):
    out = make_barcode(a.kind, a.data, a.output)
    print(f"Wrote {a.kind} barcode -> {out}")


def cmd_scan(a):
    results = scan_qr(a.image)
    if not results:
        print("No QR code found.")
        return 1
    for r in results:
        print(r)
    return 0


def cmd_batch(a):
    outs = batch_qr_from_csv(a.csv, a.out_dir, a.column,
                             name_column=a.name_column, scale=a.scale,
                             border=a.border, error=a.error, fmt=a.format)
    print(f"Generated {len(outs)} QR codes in {a.out_dir}")
    return 0


def build_parser():
    p = argparse.ArgumentParser(
        prog="qrkit", description="QR & Barcode Toolkit -- offline, open source.")
    sub = p.add_subparsers(dest="command", required=True)

    # ---- qr ----
    q = sub.add_parser("qr", help="generate a QR code")
    q.add_argument("--preset", choices=PRESETS, help="content preset")
    q.add_argument("--data", help="raw payload (or the value for url/text)")
    q.add_argument("-o", "--output", required=True, help="output .png or .svg")
    q.add_argument("--scale", type=int, default=8, help="module size in px (default 8)")
    q.add_argument("--border", type=int, default=4, help="quiet-zone modules (default 4)")
    q.add_argument("--error", choices=("l", "m", "q", "h"), default="m",
                   help="error correction (default m)")
    q.add_argument("--format", choices=("png", "svg"), default="png",
                   help="format when output has no extension")
    # url / text
    q.add_argument("--url", help="url preset: the URL")
    q.add_argument("--text", help="text preset: the text")
    # wifi
    q.add_argument("--ssid", help="wifi preset: network name")
    q.add_argument("--password", help="wifi preset: password")
    q.add_argument("--security", default="WPA", help="wifi preset: WPA/WEP/nopass")
    q.add_argument("--hidden", action="store_true", help="wifi preset: hidden network")
    # email
    q.add_argument("--to", help="email preset: recipient")
    q.add_argument("--subject", default="", help="email preset: subject")
    q.add_argument("--body", default="", help="email preset: body")
    # sms
    q.add_argument("--number", help="sms preset: phone number")
    q.add_argument("--message", default="", help="sms preset: message")
    # geo
    q.add_argument("--lat", help="geo preset: latitude")
    q.add_argument("--lon", help="geo preset: longitude")
    # vcard
    q.add_argument("--name", help="vcard: full display name")
    q.add_argument("--first-name", dest="first_name", help="vcard: first name")
    q.add_argument("--last-name", dest="last_name", help="vcard: last name")
    q.add_argument("--org", help="vcard: organisation")
    q.add_argument("--title", help="vcard: job title")
    q.add_argument("--phone", help="vcard: phone")
    q.add_argument("--email", help="vcard: email")
    q.add_argument("--vurl", help="vcard: website URL")
    q.set_defaults(func=cmd_qr)

    # ---- barcode ----
    b = sub.add_parser("barcode", help="generate a 1D barcode")
    b.add_argument("--kind", required=True,
                   help="one of: " + ", ".join(supported_kinds()))
    b.add_argument("--data", required=True, help="barcode data")
    b.add_argument("-o", "--output", required=True, help="output .png")
    b.set_defaults(func=cmd_barcode)

    # ---- scan ----
    s = sub.add_parser("scan", help="decode QR codes from an image")
    s.add_argument("image", help="image file to scan")
    s.set_defaults(func=cmd_scan)

    # ---- batch ----
    ba = sub.add_parser("batch", help="generate QRs from a CSV")
    ba.add_argument("csv", help="input CSV file")
    ba.add_argument("-d", "--out-dir", required=True, help="output directory")
    ba.add_argument("-c", "--column", required=True, help="CSV column with QR data")
    ba.add_argument("--name-column", help="CSV column to name files by")
    ba.add_argument("--scale", type=int, default=8)
    ba.add_argument("--border", type=int, default=4)
    ba.add_argument("--error", choices=("l", "m", "q", "h"), default="m")
    ba.add_argument("--format", choices=("png", "svg"), default="png")
    ba.set_defaults(func=cmd_batch)

    return p


def main(argv=None):
    """CLI entry point. Returns a process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        rc = args.func(args)
        return int(rc) if rc else 0
    except QRKitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # never dump a raw traceback at the user
        print(f"unexpected error: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
