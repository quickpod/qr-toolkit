"""1D barcode generation via `python-barcode` (PNG output through Pillow).

Supported kinds: EAN13, EAN8, UPCA, Code128, Code39.  Input validation
(checksums, length, allowed characters) is delegated to python-barcode, whose
errors are wrapped as :class:`QRKitError` with a readable message.
"""

from __future__ import annotations

import os

from .errors import QRKitError

# public kind (upper) -> python-barcode provider name (lower)
KINDS = {
    "EAN13": "ean13",
    "EAN8": "ean8",
    "UPCA": "upca",
    "CODE128": "code128",
    "CODE39": "code39",
}


def supported_kinds():
    """Return the list of accepted barcode kinds (display order)."""
    return ["EAN13", "EAN8", "UPCA", "Code128", "Code39"]


def make_barcode(kind, data, out):
    """Render *data* as a *kind* barcode PNG at *out*; return the path.

    *out* may or may not end in ``.png`` -- the writer always produces a PNG.
    """
    import barcode
    from barcode.writer import ImageWriter

    key = (kind or "").strip().upper()
    if key not in KINDS:
        raise QRKitError(
            f"Unknown barcode kind {kind!r}; choose one of "
            + ", ".join(supported_kinds())
            + "."
        )
    if data is None or str(data).strip() == "":
        raise QRKitError("Barcode data is required.")

    base = out[:-4] if out.lower().endswith(".png") else out
    parent = os.path.dirname(os.path.abspath(base))
    if parent:
        os.makedirs(parent, exist_ok=True)

    try:
        cls = barcode.get_barcode_class(KINDS[key])
        obj = cls(str(data), writer=ImageWriter())
    except Exception as exc:
        raise QRKitError(f"Invalid data for {key}: {exc}")

    try:
        return obj.save(base)
    except Exception as exc:
        raise QRKitError(f"Could not write barcode to {out}: {exc}")
