"""Batch QR generation from a CSV file -- one QR image per data row.

File names are deterministic: taken from ``name_column`` when given (sanitised),
otherwise ``row1``, ``row2`` ... in file order.  Collisions get a numeric
suffix so no output is silently overwritten.
"""

from __future__ import annotations

import csv
import os
import re

from .errors import QRKitError
from .qrgen import make_qr

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _sanitize(name, fallback):
    name = _SAFE.sub("_", str(name or "").strip()).strip("._")
    return name or fallback


def batch_qr_from_csv(csv_path, out_dir, column, name_column=None, **qr_opts):
    """Generate one QR per CSV row from *column*; return the list of paths.

    ``qr_opts`` (scale, border, error, fmt) are forwarded to
    :func:`qrkit.qrgen.make_qr`.
    """
    if not os.path.isfile(csv_path):
        raise QRKitError(f"CSV file not found: {csv_path}")

    fmt = (qr_opts.get("fmt") or "png").lower()
    os.makedirs(out_dir, exist_ok=True)

    outputs = []
    used = set()
    try:
        with open(csv_path, newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            fields = reader.fieldnames or []
            if column not in fields:
                raise QRKitError(
                    f"Column {column!r} not found in CSV. Available: "
                    + (", ".join(fields) if fields else "(none)")
                )
            if name_column and name_column not in fields:
                raise QRKitError(f"Name column {name_column!r} not found in CSV.")

            for i, row in enumerate(reader, start=1):
                data = (row.get(column) or "").strip()
                if not data:
                    continue  # skip blank rows
                if name_column:
                    stem = _sanitize(row.get(name_column), f"row{i}")
                else:
                    stem = f"row{i}"
                candidate = stem
                n = 1
                while candidate in used:
                    n += 1
                    candidate = f"{stem}_{n}"
                used.add(candidate)
                out = os.path.join(out_dir, f"{candidate}.{fmt}")
                make_qr(data, out, **qr_opts)
                outputs.append(out)
    except QRKitError:
        raise
    except Exception as exc:
        raise QRKitError(f"Batch generation failed: {exc}")

    return outputs
