"""QR & Barcode Toolkit -- a fast, offline, open-source QR/barcode library.

Public API (import from ``qrkit``):

* :func:`make_qr` and the ``preset_*`` helpers  -- QR generation (segno)
* :func:`make_barcode`                          -- 1D barcodes (python-barcode)
* :func:`scan_qr`                               -- decode QR from images (OpenCV)
* :func:`batch_qr_from_csv`                     -- batch QR from a CSV
* :class:`QRKitError`                           -- the single error type

The GUI lives in :mod:`qrkit.gui` and is imported lazily (it needs tkinter).
100% AI-built, open source, published on QuickOpen (quickopen.ai).
"""

from __future__ import annotations

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

__version__ = "1.0.7"

__all__ = [
    "QRKitError",
    "make_qr",
    "make_barcode",
    "supported_kinds",
    "scan_qr",
    "batch_qr_from_csv",
    "preset_text",
    "preset_url",
    "preset_wifi",
    "preset_vcard",
    "preset_email",
    "preset_sms",
    "preset_geo",
    "__version__",
]
