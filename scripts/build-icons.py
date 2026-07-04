#!/usr/bin/env python3
"""Rasterize icon SVGs to PNG for Chrome extension + favicons."""

from __future__ import annotations

import shutil
import struct
import subprocess
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DESIGNS = ROOT / "extension" / "icons" / "designs"
OUT = ROOT / "extension" / "dist" / "icons"
PREVIEW = ROOT / "extension" / "dist" / "icon-preview.html"
DEFAULT = "09-stripe-wave"
SIZES = (16, 32, 48, 128)


def rasterize_cairosvg(svg: Path, png: Path, size: int) -> bool:
    try:
        import cairosvg
        cairosvg.svg2png(url=str(svg), write_to=str(png), output_width=size, output_height=size)
        return True
    except Exception:
        return False


def rasterize_qlmanage(svg: Path, png: Path, size: int) -> bool:
    if not shutil.which("qlmanage"):
        return False
    tmp = png.parent / f".tmp_{png.stem}.png"
    try:
        subprocess.run(
            ["qlmanage", "-t", "-s", str(size), "-o", str(png.parent), str(svg)],
            check=True,
            capture_output=True,
        )
        generated = png.parent / f"{svg.name}.png"
        if generated.exists():
            generated.rename(png)
            return True
    except subprocess.CalledProcessError:
        pass
    return False


def rasterize(svg: Path, png: Path, size: int) -> None:
    png.parent.mkdir(parents=True, exist_ok=True)
    if rasterize_cairosvg(svg, png, size):
        return
    if rasterize_qlmanage(svg, png, size):
        return
    raise RuntimeError(
        f"Could not rasterize {svg.name}. Install: pip install cairosvg\n"
        "Or on macOS qlmanage should work automatically."
    )


def write_preview_html() -> None:
    svgs = sorted(DESIGNS.glob("*.svg"))
    bull = sorted([s for s in svgs if s.stem.startswith("bull-")])
    other = sorted([s for s in svgs if not s.stem.startswith("bull-")])

    def cards(items: list[Path]) -> str:
        out = []
        for svg in items:
            name = svg.stem
            badge = ' <span style="color:#e8622a;font-size:10px">default</span>' if name == DEFAULT else ""
            # PNG previews live inside dist/ so file:// gallery works in Chrome
            png = f"icons/variants/{name}-128.png"
            out.append(f"""
        <div class="card">
          <img src="{png}" width="128" height="128" alt="{name}" loading="lazy"
               onerror="this.src='icons/icon128.png'; this.alt='missing'" />
          <h3>{name.replace('-', ' ').title()}{badge}</h3>
          <code>python3 scripts/build-icons.py {name}</code>
        </div>""")
        return "".join(out)

    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"/>
<title>Market Morning — Icon Gallery</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;600&family=Instrument+Serif&display=swap" rel="stylesheet"/>
<style>
  body {{ font-family: 'DM Sans', sans-serif; background: #f6f4ef; color: #0a0a0a; padding: 32px; max-width: 960px; margin: 0 auto; }}
  h1 {{ font-family: 'Instrument Serif', serif; font-weight: 400; font-size: 32px; letter-spacing: -0.03em; }}
  h2 {{ font-size: 14px; text-transform: uppercase; letter-spacing: 0.1em; color: #1a3c34; margin: 36px 0 16px; }}
  p {{ color: #6b7280; max-width: 560px; line-height: 1.6; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 20px; }}
  .card {{ background: #fff; border-radius: 16px; padding: 20px; text-align: center; border: 1px solid rgba(0,0,0,0.06); }}
  .card img {{ border-radius: 22%; margin-bottom: 12px; }}
  .card h3 {{ font-size: 13px; margin: 0 0 8px; font-weight: 600; }}
  .card code {{ font-size: 10px; color: #1a3c34; word-break: break-all; display: block; }}
</style></head><body>
<h1>Market Morning Icons</h1>
<p>Bullish-themed variants plus original minimal fintech logos. Apply with the command under each card, then reload the extension.</p>
<p style="font-size:13px;color:#1a3c34">Tip: previews use PNGs in <code>icons/variants/</code> so they work when opened locally in Chrome.</p>
<p style="font-size:13px;color:#1a3c34">Tip: if images don't load, refresh this page — previews use PNGs from <code>icons/variants/</code>.</p>
<h2>Bullish 🐂</h2>
<div class="grid">{cards(bull)}</div>
<h2>Other</h2>
<div class="grid">{cards(other)}</div>
</body></html>"""
    PREVIEW.write_text(html)


def apply_design(name: str) -> None:
    svg = DESIGNS / f"{name}.svg"
    if not svg.exists():
        # allow passing full filename
        svg = DESIGNS / name if name.endswith(".svg") else None
        if svg is None or not svg.exists():
            raise SystemExit(f"Design not found: {name}\nAvailable: {[p.stem for p in DESIGNS.glob('*.svg')]}")

    if not svg.name.endswith(".svg"):
        svg = DESIGNS / f"{name}.svg"

    for size in SIZES:
        out = OUT / f"icon{size}.png"
        rasterize(svg, out, size)
        print(f"  icon{size}.png")

    # Favicon copies
    favicon_dir = ROOT / "extension" / "dist"
    rasterize(svg, favicon_dir / "favicon-32.png", 32)
    rasterize(svg, favicon_dir / "favicon-48.png", 48)
    shutil.copy2(svg, favicon_dir / "favicon.svg")
    print(f"Applied: {svg.stem}")


def build_all_variants() -> None:
    variants_dir = OUT / "variants"
    variants_dir.mkdir(parents=True, exist_ok=True)
    # Copy SVGs into dist for local reference
    designs_out = OUT / "designs"
    designs_out.mkdir(parents=True, exist_ok=True)
    for svg in sorted(DESIGNS.glob("*.svg")):
        shutil.copy2(svg, designs_out / svg.name)
        for size in (128,):
            out = variants_dir / f"{svg.stem}-{size}.png"
            rasterize(svg, out, size)
            print(f"  {out.relative_to(ROOT)}")


def main() -> None:
    write_preview_html()
    print(f"Preview: extension/dist/icon-preview.html")

    name = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    if name == "--all":
        build_all_variants()
        apply_design(DEFAULT)
        write_preview_html()
        return

    apply_design(name)
    build_all_variants()
    write_preview_html()


if __name__ == "__main__":
    main()
