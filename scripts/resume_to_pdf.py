# -*- coding: utf-8 -*-
"""Render resume Markdown to PDF via Chrome headless."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent.parent
# Resume Markdown / PDF filenames (Unicode escapes keep .py ASCII-only on Windows)
MD_NAME = "\u5bcc\u5065\u54f2_AI\u5927\u6a21\u578b\u5de5\u7a0b\u5e08_\u7b80\u5386.md"
OUT_NAME = "\u5bcc\u5065\u54f2_AI\u5927\u6a21\u578b\u5de5\u7a0b\u5e08_\u7b80\u5386.pdf"


def _find_chrome() -> Path:
    candidates = [
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
        / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
        / "Microsoft/Edge/Application/msedge.exe",
    ]
    for p in candidates:
        if p.is_file():
            return p
    raise FileNotFoundError("Chrome or Edge not found. Install a Chromium-based browser.")


def main() -> int:
    md_path = ROOT / MD_NAME
    if not md_path.is_file():
        print(f"Missing source file: {md_path}", file=sys.stderr)
        return 1

    text = md_path.read_text(encoding="utf-8")
    text = re.sub(r"<style>.*?</style>\s*", "", text, flags=re.DOTALL | re.IGNORECASE)
    body = markdown.markdown(
        text,
        extensions=["extra", "nl2br", "sane_lists"],
    )
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<style>
@page {{ margin: 18mm 16mm; }}
body {{
  font-family: "Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", SimSun, sans-serif;
  font-size: 10.5pt;
  line-height: 1.5;
  color: #111827;
}}
h1 {{
  font-size: 20pt;
  font-weight: 700;
  color: #030712;
  margin: 0 0 12pt 0;
}}
h2 {{
  font-size: 12pt;
  font-weight: 700;
  color: #030712;
  margin: 16pt 0 8pt 0;
  border-bottom: 1px solid #e5e7eb;
  padding-bottom: 4px;
}}
h3 {{
  font-size: 11pt;
  margin: 10pt 0 6pt 0;
}}
p, li {{ margin: 4pt 0; }}
ul {{ margin: 4pt 0 6pt 18pt; }}
a {{ color: #2563eb; text-decoration: none; }}
strong {{ color: #030712; }}
hr {{
  border: none;
  border-top: 1px solid #e5e7eb;
  margin: 10pt 0;
}}
</style>
</head>
<body>
{body}
</body>
</html>"""

    html_path = ROOT / "_resume_print.html"
    html_path.write_text(html, encoding="utf-8")
    out_pdf = ROOT / OUT_NAME
    chrome = _find_chrome()
    url = html_path.resolve().as_uri()
    cmd = [
        str(chrome),
        "--headless=new",
        "--disable-gpu",
        f"--print-to-pdf={out_pdf.resolve()}",
        "--no-pdf-header-footer",
        url,
    ]
    try:
        subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.CalledProcessError as e:
        print(e.stderr or e.stdout, file=sys.stderr)
        return e.returncode
    finally:
        try:
            html_path.unlink(missing_ok=True)
        except OSError:
            pass

    print(out_pdf)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
