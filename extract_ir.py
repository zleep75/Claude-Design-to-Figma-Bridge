#!/usr/bin/env python3
"""
extract_ir.py — Conversion end of the Claude Design <-> Figma bridge.

Reads a Claude Design "Save as folder" / Claude Code handoff export (the .jsx
source, not the flattened HTML) and emits a Design Interaction Spec (DIS) — the
JSON contract defined in references/ir-contract.md.

What it extracts deterministically (no browser needed):
  - tokens   : the design-token object (colors / font / radii)
  - components: the reusable component inventory (atoms + per-screen components)
  - screens  : one entry per state in the flow, mapped to its component
  - flow     : the state machine — initial screen + every transition edge,
               recovered from the router's go() calls, with trigger intent
               and side effects (e.g. state reset on restart)

What it does NOT do: per-screen frame geometry. That needs a render pass over
the runnable bundle (see references/figma-mapping.md). Geometry is left as
`frame: null` for a downstream renderer to fill in.

Usage:
    python extract_ir.py <export_dir> [-o out.json] [--name "Project name"]
"""

import argparse
import json
import re
import sys
from pathlib import Path

# Map a router prop name to a human interaction intent. The point is that the
# Figma side wants intent ("this is the primary advance", "this is a back nav"),
# not the literal handler name.
INTENT_BY_PROP = {
    "onStart": "advance",
    "onNext": "advance",
    "onComplete": "advance",
    "onBack": "back",
    "onManual": "branch",
    "onAskWelly": "branch",
    "onRestart": "restart",
}


def read(export_dir: Path, name: str) -> str | None:
    p = export_dir / name
    return p.read_text(encoding="utf-8") if p.exists() else None


def find_token_file(export_dir: Path) -> tuple[str, str] | None:
    """Return (filename, text) of the file declaring the token object."""
    for p in sorted(export_dir.glob("*.jsx")):
        txt = p.read_text(encoding="utf-8")
        if re.search(r"const\s+\w+\s*=\s*\{[^}]*?#[0-9A-Fa-f]{3,8}", txt, re.S):
            return p.name, txt
    return None


def extract_tokens(token_text: str) -> tuple[str, dict]:
    """Extract the first `const NAME = { ... }` object that contains hex colors."""
    m = re.search(r"const\s+(\w+)\s*=\s*\{(.*?)\n\};", token_text, re.S)
    if not m:
        return "WC", {"color": {}, "typography": {}, "radius": {}}
    ns, body = m.group(1), m.group(2)
    color, typography = {}, {}
    for key, val in re.findall(r"(\w+)\s*:\s*'([^']*)'", body):
        if re.fullmatch(r"#[0-9A-Fa-f]{3,8}", val):
            color[key] = val
        elif "font" in key.lower() or "-apple-system" in val or "sans-serif" in val:
            typography[key] = val
    return ns, {"color": color, "typography": typography, "radius": {}}


def extract_exports(export_dir: Path) -> list[dict]:
    """Component inventory from `Object.assign(window, { A, B, ... })` lines."""
    comps, seen = [], set()
    for p in sorted(export_dir.glob("*.jsx")):
        txt = p.read_text(encoding="utf-8")
        for block in re.findall(r"Object\.assign\(window,\s*\{([^}]*)\}", txt):
            for ident in re.findall(r"[A-Za-z_]\w*", block):
                # keep PascalCase identifiers (React components), skip data globals
                if ident[:1].isupper() and ident not in seen and not ident.isupper():
                    seen.add(ident)
                    comps.append({"id": ident, "source": p.name})
    return comps


def extract_flow(app_text: str) -> tuple[dict, list, dict]:
    """Parse FLOW + the router branches inside the App's phone switcher."""
    # 1) FLOW array: { id:'welcome', label:'入口' }
    flow_entries = re.findall(r"\{\s*id\s*:\s*'(\w+)'\s*,\s*label\s*:\s*'([^']*)'", app_text)
    screens, screen_to_comp = {}, {}
    for i, (sid, label) in enumerate(flow_entries, start=1):
        screens[sid] = {"id": sid, "label": label, "step": i,
                        "component": None, "frame": None}

    # 2) Router branches: one per line, e.g.
    #    if (view==='welcome') el = <Welcome onStart={()=>go('chat')} ... />;
    # Arrow functions (`()=>`) and nested braces (`{ setCollected({}); ... }`)
    # break naive bracket matching, so we work positionally: associate each
    # go('target') with the nearest preceding on*-handler on the same line.
    transitions = []
    for line in app_text.splitlines():
        if "el =" not in line or "<" not in line:
            continue
        m = re.search(r"view\s*===\s*'(\w+)'.*?el\s*=\s*<(\w+)", line)
        if not m:
            continue
        sid, comp = m.group(1), m.group(2)
        screen_to_comp[sid] = comp
        screens.setdefault(sid, {"id": sid, "label": sid, "step": None,
                                 "component": None, "frame": None})
        screens[sid]["component"] = comp

        props = [(mm.start(), mm.group(1))
                 for mm in re.finditer(r"(on[A-Z]\w*)\s*=\s*\{", line)]
        resets = [mm.start()
                  for mm in re.finditer(r"setCollected\(\s*\{\s*\}\s*\)", line)]
        for gm in re.finditer(r"go\('(\w+)'\)", line):
            gpos, target = gm.start(), gm.group(1)
            owners = [(pos, name) for pos, name in props if pos < gpos]
            if not owners:
                continue
            owner_pos, prop = owners[-1]
            side = ["resetState"] if any(owner_pos < r < gpos for r in resets) else []
            transitions.append({
                "from": sid,
                "trigger": "onClick",
                "intent": INTENT_BY_PROP.get(prop, "navigate"),
                "element": prop,
                "to": target,
                "animation": "smartAnimate",
                "sideEffects": side,
            })

    initial = flow_entries[0][0] if flow_entries else (
        screen_to_comp and next(iter(screen_to_comp)))
    flow = {"initial": initial, "transitions": transitions}
    return flow, list(screens.values()), screen_to_comp


def extract_persona(token_text: str) -> dict | None:
    m = re.search(r"const\s+PERSONA\s*=\s*\{(.*?)\n\};", token_text, re.S)
    if not m:
        return None
    persona = {}
    for k, v in re.findall(r"(\w+)\s*:\s*'([^']*)'", m.group(1)):
        persona[k] = v
    return persona or None


def detect_lossy(export_dir: Path, screen_to_comp: dict) -> list[dict]:
    """Flag in-screen animations that Figma's prototype model can't run."""
    comp_to_screen = {c: s for s, c in screen_to_comp.items()}
    lossy = []
    for p in sorted(export_dir.glob("*.jsx")):
        txt = p.read_text(encoding="utf-8")
        for comp in re.findall(r"^function\s+(\w+)", txt, re.M):
            sid = comp_to_screen.get(comp)
            if not sid:
                continue
            seg = txt[txt.index(f"function {comp}"):]
            if re.search(r"setTimeout|setInterval", seg[:4000]):
                lossy.append({"screen": sid, "kind": "scripted-timing",
                              "note": "JS timers drive this screen; Figma can show "
                                      "end-state or a 2-frame smart-animate only."})
            if re.search(r"stroke-dashoffset|strokeDashoffset", seg[:4000]):
                lossy.append({"screen": sid, "kind": "animated-progress",
                              "note": "CSS-transition progress (e.g. ring); not "
                                      "runtime in Figma — bake start/end frames."})
    # de-dup
    uniq = {(d["screen"], d["kind"]): d for d in lossy}
    return list(uniq.values())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("export_dir", type=Path)
    ap.add_argument("-o", "--out", type=Path, default=None)
    ap.add_argument("--name", default=None)
    args = ap.parse_args()

    d = args.export_dir
    if not d.is_dir():
        print(f"not a directory: {d}", file=sys.stderr)
        return 1

    tok = find_token_file(d)
    if not tok:
        print("no token file found (expected a *.jsx with a hex-color object)",
              file=sys.stderr)
        return 1
    tok_name, tok_text = tok
    ns, tokens = extract_tokens(tok_text)

    # locate the app/router file (has FLOW + view=== branches)
    app_text = None
    for p in sorted(d.glob("*.jsx")):
        t = p.read_text(encoding="utf-8")
        if "FLOW" in t and "view===" in t.replace(" ", ""):
            app_text = t
            break
    if app_text is None:
        print("no router file found (expected FLOW + view=== branches)",
              file=sys.stderr)
        return 1

    flow, screens, s2c = extract_flow(app_text)
    components = extract_exports(d)
    persona = extract_persona(tok_text)
    lossy = detect_lossy(d, s2c)

    ir = {
        "version": "0.1",
        "meta": {
            "name": args.name or d.name,
            "source": "claude-design",
            "tokenNamespace": ns,
            **({"persona": persona} if persona else {}),
        },
        "tokens": tokens,
        "components": components,
        "screens": screens,
        "flow": flow,
        "lossy": lossy,
    }

    out = json.dumps(ir, ensure_ascii=False, indent=2)
    if args.out:
        args.out.write_text(out, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
