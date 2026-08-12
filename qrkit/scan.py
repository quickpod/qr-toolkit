"""Decode QR codes from an image file using OpenCV (no pyzbar/zbar).

Uses ``cv2.QRCodeDetector``: it tries the multi-code path first
(``detectAndDecodeMulti``) and falls back to the single-code path, returning
every non-empty decoded string it finds.
"""

from __future__ import annotations

from .errors import QRKitError


def scan_qr(image_path):
    """Return a list of decoded QR strings from *image_path* (empty if none)."""
    import cv2

    img = cv2.imread(str(image_path))
    if img is None:
        raise QRKitError(f"Could not read image: {image_path}")

    detector = cv2.QRCodeDetector()
    results = []

    try:
        ok, decoded, points, _ = detector.detectAndDecodeMulti(img)
        if ok and decoded is not None:
            results = [d for d in decoded if d]
    except Exception:
        results = []

    if not results:
        try:
            data, points, _ = detector.detectAndDecode(img)
            if data:
                results = [data]
        except Exception:
            results = []

    return results
