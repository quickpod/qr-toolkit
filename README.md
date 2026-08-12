# QR & Barcode Toolkit

A fast, **offline**, **100% open-source** QR & barcode toolkit for Windows. Nothing is uploaded anywhere. Built entirely by AI with human testing and guidance, and published on [QuickOpen](https://quickopen.ai/projects/qr-toolkit).

> **100% AI-built and open source.** Apache-2.0.

## What it does

Generate QR codes (with presets for URL, Wi-Fi, vCard, email, SMS, geo, and plain text), and common 1D barcodes (EAN/UPC/Code128/Code39). Scan/decode QR codes from image files via OpenCV. Batch-generate from a CSV, control size/margin/error-correction, and export PNG/SVG. Fully offline.

## Install

Download **`QRToolkit-Setup.exe`** from the [QuickOpen page](https://quickopen.ai/projects/qr-toolkit) or the [GitHub release](https://github.com/quickpod/qr-toolkit/releases/latest) and double-click it. It installs per-user, adds Desktop and Start Menu shortcuts, and can optionally trust the QuickOpen Root CA. Authenticode-signed by the QuickOpen Code Signing CA — verify at [quickopen.ai/trust](https://quickopen.ai/trust).

## Run from source

```sh
pip install -r requirements.txt
python qr_toolkit_app.py          # GUI
python -m qrkit --help    # CLI
```


## Features

- **QR codes** with content presets that build the correct payload for you:
  - **URL** (bare hosts get an `https://` scheme), **Text**, **Wi-Fi** join
    codes (`WIFI:`), **vCard** contacts, **Email** (`mailto:`), **SMS**
    (`SMSTO:`) and **Geo** (`geo:`) locations.
  - Control module **scale**, quiet-zone **border** and **error correction**
    (L/M/Q/H); export **PNG** or **SVG**.
- **1D barcodes**: EAN13, EAN8, UPCA, Code128, Code39 (PNG via Pillow). Checksums
  and input validation are handled for you.
- **Scan / decode** QR codes from any image (PNG/JPG/…) with OpenCV — no native
  zbar DLL required. Reads multiple codes per image.
- **Batch** generation: one QR per row of a CSV column, with deterministic file
  names (from a name column, or `row1`, `row2`, …).
- **Desktop GUI** (tkinter): sidebar navigation, live image preview, light/dark
  mode, recent files, threaded generation/scanning, and PNG/SVG export.
- **Fully offline.** Nothing is ever uploaded anywhere.

## CLI examples

```sh
# QR from a URL preset -> PNG
python -m qrkit qr --preset url --url quickopen.ai -o site.png

# Wi-Fi join code, high error correction
python -m qrkit qr --preset wifi --ssid CoffeeShop --password beans123 \
    --security WPA --error h -o wifi.png

# vCard contact -> SVG
python -m qrkit qr --preset vcard --name "Ada Lovelace" \
    --email ada@example.com --phone +15551234567 -o ada.svg --format svg

# Email / SMS / Geo presets
python -m qrkit qr --preset email --to hi@example.com --subject "Hello" -o mail.png
python -m qrkit qr --preset sms --number +15551234567 --message "On my way" -o sms.png
python -m qrkit qr --preset geo --lat 37.7749 --lon -122.4194 -o where.png

# 1D barcodes
python -m qrkit barcode --kind Code128 --data "SHIP-99887" -o parcel.png
python -m qrkit barcode --kind EAN13 --data 590123412345 -o product.png

# Scan / decode QR codes from an image (prints one per line)
python -m qrkit scan wifi.png

# Batch: one QR per CSV row (column "link"), named by column "name"
python -m qrkit batch contacts.csv -d ./out -c link --name-column name
```

## License

Apache-2.0 — see [LICENSE](LICENSE). A 100% AI-built project published on QuickOpen.
