"""QR-code generation and content presets, built on `segno`.

`make_qr` renders any string payload to a PNG or SVG.  The ``preset_*`` helpers
build the *right* payload string for a given content type (URL, Wi-Fi, vCard,
email, SMS, geo, plain text) following the widely-supported de-facto encodings
that phone cameras recognise.  Presets only build strings -- callers pass the
result to :func:`make_qr`.
"""

from __future__ import annotations

import os
from urllib.parse import quote

from .errors import QRKitError

VALID_ERROR = ("l", "m", "q", "h")
VALID_FORMATS = ("png", "svg")


def make_qr(data, out, scale=8, border=4, error="m", fmt="png"):
    """Render *data* to a QR code image at *out*.

    ``scale`` is the module (pixel) size, ``border`` the quiet-zone width in
    modules, ``error`` one of l/m/q/h (low..high correction).  The output format
    is taken from the *out* file extension when present, otherwise from *fmt*
    (``png`` or ``svg``).  Returns the output path.
    """
    import segno

    if data is None or data == "":
        raise QRKitError("Nothing to encode: the QR content is empty.")
    err = (error or "m").lower()
    if err not in VALID_ERROR:
        raise QRKitError(f"Invalid error level {error!r}; use one of l, m, q, h.")

    ext = os.path.splitext(out)[1].lower().lstrip(".")
    kind = ext or (fmt or "png").lower()
    if kind not in VALID_FORMATS:
        raise QRKitError(f"Unsupported format {kind!r}; use png or svg.")

    try:
        scale = int(scale)
        border = int(border)
    except (TypeError, ValueError):
        raise QRKitError("scale and border must be whole numbers.")
    if scale < 1:
        raise QRKitError("scale must be at least 1.")
    if border < 0:
        raise QRKitError("border must be 0 or greater.")

    try:
        qr = segno.make(str(data), error=err)
    except Exception as exc:
        raise QRKitError(f"Could not build the QR code: {exc}")

    parent = os.path.dirname(os.path.abspath(out))
    try:
        if parent:
            os.makedirs(parent, exist_ok=True)
        if ext:
            qr.save(out, scale=scale, border=border)
        else:
            qr.save(out, kind=kind, scale=scale, border=border)
    except Exception as exc:
        raise QRKitError(f"Could not write {out}: {exc}")
    return out


# ---------------------------------------------------------------------------
# Content presets -- each returns the payload STRING to encode.
# ---------------------------------------------------------------------------
def preset_text(text):
    """Plain text, encoded verbatim."""
    if text is None:
        raise QRKitError("Text is required.")
    return str(text)


def preset_url(url):
    """A URL. A bare host gets an ``https://`` scheme so cameras open it."""
    url = (url or "").strip()
    if not url:
        raise QRKitError("A URL is required.")
    if "://" not in url and not url.lower().startswith("mailto:"):
        url = "https://" + url
    return url


def _wifi_escape(value):
    """Escape the Wi-Fi reserved characters ``\\ ; , : "``."""
    out = []
    for ch in str(value or ""):
        if ch in "\\;,:\"":
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)


def preset_wifi(ssid, password, security="WPA", hidden=False):
    """A ``WIFI:`` join string. ``security`` is WPA / WEP / nopass."""
    ssid = (ssid or "").strip()
    if not ssid:
        raise QRKitError("A Wi-Fi network name (SSID) is required.")
    sec = (security or "WPA").strip().upper()
    if sec in ("", "NONE", "OPEN", "NOPASS"):
        sec = "nopass"
    if sec not in ("WPA", "WEP", "nopass"):
        raise QRKitError("Wi-Fi security must be WPA, WEP or nopass.")
    parts = [f"WIFI:T:{sec};S:{_wifi_escape(ssid)};"]
    if sec != "nopass":
        parts.append(f"P:{_wifi_escape(password)};")
    if hidden:
        parts.append("H:true;")
    parts.append(";")
    return "".join(parts)


def preset_vcard(fields):
    """A vCard 3.0 from a dict of fields.

    Recognised keys: ``first_name``, ``last_name`` (or ``name`` for the full
    display name), ``org``, ``title``, ``phone``, ``email``, ``url``,
    ``street``, ``city``, ``region``, ``zip``, ``country``.
    """
    if not isinstance(fields, dict):
        raise QRKitError("vCard fields must be a mapping.")

    def g(key):
        return str(fields.get(key, "") or "").strip()

    first, last = g("first_name"), g("last_name")
    full = g("name") or " ".join(p for p in (first, last) if p)
    if not full and not any(g(k) for k in ("org", "phone", "email")):
        raise QRKitError("A vCard needs at least a name, organisation, phone or email.")

    lines = ["BEGIN:VCARD", "VERSION:3.0"]
    lines.append(f"N:{last};{first};;;")
    lines.append(f"FN:{full}")
    if g("org"):
        lines.append(f"ORG:{g('org')}")
    if g("title"):
        lines.append(f"TITLE:{g('title')}")
    if g("phone"):
        lines.append(f"TEL;TYPE=CELL:{g('phone')}")
    if g("email"):
        lines.append(f"EMAIL:{g('email')}")
    if g("url"):
        lines.append(f"URL:{g('url')}")
    if any(g(k) for k in ("street", "city", "region", "zip", "country")):
        lines.append(
            "ADR;TYPE=HOME:;;"
            f"{g('street')};{g('city')};{g('region')};{g('zip')};{g('country')}"
        )
    lines.append("END:VCARD")
    return "\r\n".join(lines)


def preset_email(to, subject="", body=""):
    """A ``mailto:`` link with optional subject/body."""
    to = (to or "").strip()
    if not to:
        raise QRKitError("A destination email address is required.")
    params = []
    if subject:
        params.append("subject=" + quote(str(subject)))
    if body:
        params.append("body=" + quote(str(body)))
    query = ("?" + "&".join(params)) if params else ""
    return f"mailto:{to}{query}"


def preset_sms(number, message=""):
    """An ``SMSTO:`` payload (number + optional prefilled message)."""
    number = (number or "").strip()
    if not number:
        raise QRKitError("A phone number is required.")
    if message:
        return f"SMSTO:{number}:{message}"
    return f"SMSTO:{number}:"


def preset_geo(lat, lon):
    """A ``geo:`` URI for a latitude/longitude pair."""
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (TypeError, ValueError):
        raise QRKitError("Latitude and longitude must be numbers.")
    return f"geo:{lat_f},{lon_f}"
