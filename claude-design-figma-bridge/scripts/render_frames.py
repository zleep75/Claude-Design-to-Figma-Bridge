#!/usr/bin/env python3
"""
render_frames.py — fills the geometry that extract_ir.py leaves as `frame: null`.

extract_ir.py recovers tokens + the flow graph statically (no browser). This
second pass needs to actually *run* the UI to know where things are. The
cleanest geometry source is the export's per-screen standalone HTML
(`figma-screens/*.html`) — each one is a full render of a single screen, which
is exactly one Figma frame. (The flow that connects them came from app.jsx.)

It loads each screen in headless Chromium (Playwright), waits for React to
mount, then walks the DOM capturing position + key computed styles into a layout
tree, and merges that into `screens[].frame`. Layer names prefer a
`data-figma-name` / `data-name` attribute when present (see the generation rules
in SKILL.md) and fall back to a content/path heuristic — stable names are what
let Smart Animate bind shared elements across frames.

Setup (needs network once, to fetch the browser binary):
    pip install playwright
    playwright install chromium

Usage:
    python render_frames.py <export_dir> <ir.json> [-o out.ir.json]
"""

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

# JS injected into each page. Returns the phone frame's geometry + a flat-ish
# node tree with positions relative to the frame origin and the styles Figma
# needs to rebuild the layout.
WALK_JS = r"""
() => {
  const SKIP = new Set(['SCRIPT','STYLE','NOSCRIPT','LINK','META']);
  // The bundler shows a placeholder until React mounts; ignore its chrome.
  const root = document.querySelector('#root') ||
               document.querySelector('[data-app-root]') ||
               document.body;
  // Pick the largest visible element as the "phone" frame.
  let frameEl = root, best = 0;
  root.querySelectorAll('*').forEach(el => {
    const r = el.getBoundingClientRect();
    if (r.width > 200 && r.height > 300 && r.width * r.height > best &&
        r.width < window.innerWidth) { best = r.width * r.height; frameEl = el; }
  });
  const base = frameEl.getBoundingClientRect();
  const px = v => Math.round(parseFloat(v) || 0);
  const nameOf = (el, i) => el.getAttribute('data-figma-name') ||
      el.getAttribute('data-name') ||
      (el.childElementCount === 0 && el.textContent.trim()
        ? el.textContent.trim().slice(0, 24)
        : el.tagName.toLowerCase() + '-' + i);

  const nodes = [];
  let i = 0;
  const visit = (el, depth) => {
    if (SKIP.has(el.tagName) || depth > 12) return;
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return;
    const cs = getComputedStyle(el);
    const isLeafText = el.childElementCount === 0 && el.textContent.trim();
    nodes.push({
      name: nameOf(el, i++),
      type: isLeafText ? 'TEXT' : 'FRAME',
      x: Math.round(r.left - base.left),
      y: Math.round(r.top - base.top),
      w: Math.round(r.width),
      h: Math.round(r.height),
      depth,
      style: {
        background: cs.backgroundColor,
        color: cs.color,
        fontSize: px(cs.fontSize),
        fontWeight: cs.fontWeight,
        radius: px(cs.borderTopLeftRadius),
        opacity: parseFloat(cs.opacity),
        display: cs.display,
        flexDirection: cs.flexDirection,
        gap: px(cs.gap),
        padding: [px(cs.paddingTop), px(cs.paddingRight),
                  px(cs.paddingBottom), px(cs.paddingLeft)],
      },
      ...(isLeafText ? { text: el.textContent.trim() } : {}),
    });
    for (const child of el.children) visit(child, depth + 1);
  };
  for (const child of frameEl.children) visit(child, 0);
  return { width: Math.round(base.width), height: Math.round(base.height), nodes };
}
"""


def screen_html_map(export_dir: Path) -> dict[int, Path]:
    """Map a 1-based screen index to its standalone HTML, by the NN- prefix."""
    out = {}
    d = export_dir / "figma-screens"
    if not d.is_dir():
        return out
    for p in d.glob("*.html"):
        m = re.match(r"(\d+)", p.name)
        if m:
            out[int(m.group(1))] = p
    return out


async def render(export_dir: Path, ir: dict) -> dict:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("Playwright not installed. Run:\n"
              "  pip install playwright && playwright install chromium",
              file=sys.stderr)
        raise

    html_by_index = screen_html_map(export_dir)
    if not html_by_index:
        print("no figma-screens/*.html found — nothing to render. The flow IR is "
              "still complete; geometry just stays null.", file=sys.stderr)
        return ir

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page(viewport={"width": 1280, "height": 900})
        # screens that have a standalone render, in flow order
        renderable = [s for s in ir["screens"] if s.get("step")]
        renderable.sort(key=lambda s: s["step"])
        for s in renderable:
            html = html_by_index.get(s["step"])
            if not html:
                print(f"  · {s['id']}: no standalone HTML (e.g. branch screen) — skipped")
                continue
            await page.goto(html.resolve().as_uri())
            # wait for React to replace the bundler placeholder
            try:
                await page.wait_for_function(
                    "document.querySelector('#__bundler_thumbnail') === null || "
                    "document.querySelectorAll('#root *, body *').length > 30",
                    timeout=15000)
            except Exception:
                pass
            await page.wait_for_timeout(600)
            frame = await page.evaluate(WALK_JS)
            s["frame"] = frame
            print(f"  · {s['id']}: {frame['width']}x{frame['height']}, "
                  f"{len(frame['nodes'])} nodes")
        await browser.close()
    return ir


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("export_dir", type=Path)
    ap.add_argument("ir", type=Path)
    ap.add_argument("-o", "--out", type=Path, default=None)
    args = ap.parse_args()

    ir = json.loads(args.ir.read_text(encoding="utf-8"))
    ir = asyncio.run(render(args.export_dir, ir))

    out = args.out or args.ir
    out.write_text(json.dumps(ir, ensure_ascii=False, indent=2), encoding="utf-8")
    filled = sum(1 for s in ir["screens"] if s.get("frame"))
    print(f"wrote {out} — {filled}/{len(ir['screens'])} screens have geometry")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
