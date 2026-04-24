# Termux Headless Guide

This guide shows how to run **IntenseRP Next** in Termux without the PySide6 desktop UI.

## 1) Install Termux packages

```bash
pkg update -y && pkg upgrade -y
pkg install -y git python rust clang libxml2 libxslt openssl
pkg install -y chromium zip
```

> Chromium is required for provider automation in headless/headed runtime.

## 2) Clone and install Python dependencies

```bash
git clone https://github.com/LyubomirT/intense-rp-next.git
cd intense-rp-next
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip wheel
pip install -r requirements.txt
```

## 3) First startup (recommended for CAPTCHA/login)

Run once in headed mode:

```bash
python headless_main.py --headed
```

- Solve login/CAPTCHA in the opened browser.
- Keep **Persistent Sessions** enabled so login cookies are reused.

Then run normal headless mode:

```bash
python headless_main.py
```

## 4) Open the web settings dashboard

Default URL:

```text
http://127.0.0.1:7777/settings
```

From there you can edit saved settings without the desktop GUI.

## 5) Optional runtime flags

```bash
python headless_main.py --host 0.0.0.0 --port 7777
python headless_main.py --headed
python headless_main.py --headless
```

## 6) Chromium override (if auto-detect fails)

```bash
export IRP_CHROMIUM_EXECUTABLE=/absolute/path/to/chromium
python headless_main.py
```
