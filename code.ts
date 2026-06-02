// code.ts — the consumer end of the Design Interaction Spec.
// Turns a DIS document into a real Figma prototype: token Variables, one frame
// per screen, and a Reaction per flow edge. Geometry (screens[].frame) is used
// when present; otherwise screens become labeled placeholder frames so the
// prototype graph is still navigable.
//
// Implements references/figma-mapping.md. Build with `tsc`, run in Figma.

/* ---------- DIS types (subset we consume) ---------- */
interface Token { [name: string]: string }
interface DISNode {
  name: string; type: "FRAME" | "TEXT";
  x: number; y: number; w: number; h: number;
  text?: string;
  style?: {
    background?: string; color?: string; fontSize?: number;
    radius?: number; opacity?: number;
  };
}
interface DISFrame { width: number; height: number; nodes: DISNode[] }
interface DISScreen {
  id: string; label?: string; step?: number | null;
  component?: string | null; frame?: DISFrame | null;
}
interface DISTransition {
  from: string; to: string; trigger: string;
  intent?: string; element?: string; animation?: string;
  delayMs?: number; sideEffects?: string[];
}
interface DIS {
  version: string;
  tokens: { color?: Token; radius?: Record<string, number | string> };
  screens: DISScreen[];
  flow: { initial: string; transitions: DISTransition[] };
  lossy?: { screen: string; kind: string; note?: string }[];
}

/* ---------- helpers ---------- */
function hexToRgb(hex: string): RGB {
  let h = hex.replace("#", "");
  if (h.length === 3) h = h.split("").map((c) => c + c).join("");
  const n = parseInt(h.slice(0, 6), 16);
  return { r: ((n >> 16) & 255) / 255, g: ((n >> 8) & 255) / 255, b: (n & 255) / 255 };
}

function cssColorToRgb(css?: string): RGB | null {
  if (!css) return null;
  if (css.startsWith("#")) return hexToRgb(css);
  const m = css.match(/rgba?\(([^)]+)\)/);
  if (!m) return null;
  const p = m[1].split(",").map((s) => parseFloat(s));
  if (p[3] === 0) return null; // transparent
  return { r: p[0] / 255, g: p[1] / 255, b: p[2] / 255 };
}

const ANIM: Record<string, Transition | null> = {
  smartAnimate: { type: "SMART_ANIMATE", easing: { type: "EASE_OUT" }, duration: 0.3 },
  dissolve: { type: "DISSOLVE", easing: { type: "EASE_OUT" }, duration: 0.3 },
  instant: null,
};

// intent → a directional default so edges look right without per-edge config
function transitionFor(t: DISTransition): Transition | null {
  if (t.animation && t.animation in ANIM) return ANIM[t.animation];
  if (t.intent === "back") return { type: "MOVE_IN", direction: "RIGHT", matchLayers: false, easing: { type: "EASE_OUT" }, duration: 0.3 };
  if (t.intent === "advance") return { type: "MOVE_IN", direction: "LEFT", matchLayers: false, easing: { type: "EASE_OUT" }, duration: 0.3 };
  return ANIM.smartAnimate;
}

/* ---------- build ---------- */
async function createColorVariables(tokens: DIS["tokens"]): Promise<void> {
  const colors = tokens.color || {};
  if (Object.keys(colors).length === 0) return;
  const col = figma.variables.createVariableCollection("tokens/color");
  const mode = col.modes[0].modeId;
  for (const [name, hex] of Object.entries(colors)) {
    if (!/^#[0-9a-fA-F]{3,8}$/.test(hex)) continue;
    const v = figma.variables.createVariable(name, col, "COLOR");
    v.setValueForMode(mode, hexToRgb(hex));
  }
}

async function buildFrame(screen: DISScreen): Promise<FrameNode> {
  const frame = figma.createFrame();
  frame.name = screen.id;
  const geo = screen.frame;
  frame.resize(geo ? geo.width : 376, geo ? geo.height : 720);

  if (!geo) {
    // placeholder so the prototype is still navigable before the render pass
    frame.fills = [{ type: "SOLID", color: { r: 0.96, g: 0.96, b: 0.96 } }];
    const label = figma.createText();
    await figma.loadFontAsync({ family: "Inter", style: "Regular" });
    label.fontName = { family: "Inter", style: "Regular" };
    label.characters = screen.label || screen.id;
    label.x = 24; label.y = 24;
    frame.appendChild(label);
    return frame;
  }

  for (const n of geo.nodes) {
    if (n.type === "TEXT" && n.text) {
      const t = figma.createText();
      await figma.loadFontAsync({ family: "Inter", style: "Regular" });
      t.fontName = { family: "Inter", style: "Regular" };
      t.characters = n.text;
      t.x = n.x; t.y = n.y;
      if (n.style?.fontSize) t.fontSize = n.style.fontSize;
      const c = cssColorToRgb(n.style?.color);
      if (c) t.fills = [{ type: "SOLID", color: c }];
      frame.appendChild(t);
    } else {
      const r = figma.createFrame();
      r.name = n.name;          // stable name → Smart Animate can bind it
      r.x = n.x; r.y = n.y;
      r.resize(Math.max(1, n.w), Math.max(1, n.h));
      r.cornerRadius = n.style?.radius || 0;
      const bg = cssColorToRgb(n.style?.background);
      r.fills = bg ? [{ type: "SOLID", color: bg }] : [];
      if (n.style?.opacity !== undefined) r.opacity = n.style.opacity;
      frame.appendChild(r);
    }
  }
  return frame;
}

async function wireFlow(dis: DIS, frameById: Record<string, FrameNode>): Promise<string[]> {
  const warnings: string[] = [];
  for (const t of dis.flow.transitions) {
    const src = frameById[t.from];
    const dst = frameById[t.to];
    if (!src || !dst) { warnings.push(`edge ${t.from}→${t.to}: missing frame`); continue; }

    // find the triggering node by its stable name; fall back to the frame
    let trigger: SceneNode & ReactionMixin = src;
    if (t.element) {
      const hit = src.findOne((c) => c.name === t.element);
      if (hit && "setReactionsAsync" in hit) trigger = hit as SceneNode & ReactionMixin;
    }

    const reaction: Reaction = {
      trigger: { type: "ON_CLICK" },
      actions: [{
        type: "NODE",
        destinationId: dst.id,
        navigation: "NAVIGATE",
        transition: transitionFor(t),
        preserveScrollPosition: false,
      }],
    };
    const existing = trigger.reactions;
    await trigger.setReactionsAsync([...existing, reaction]);

    if (t.sideEffects && t.sideEffects.length) {
      warnings.push(`edge ${t.from}→${t.to}: side effects ${t.sideEffects.join(",")} can't run in Figma`);
    }
  }
  return warnings;
}

async function build(dis: DIS): Promise<void> {
  await createColorVariables(dis.tokens);

  const frameById: Record<string, FrameNode> = {};
  let x = 0;
  for (const screen of dis.screens) {
    const f = await buildFrame(screen);
    f.x = x; f.y = 0;
    x += f.width + 80;
    figma.currentPage.appendChild(f);
    frameById[screen.id] = f;
  }

  const warnings = await wireFlow(dis, frameById);

  const start = frameById[dis.flow.initial];
  if (start) {
    figma.currentPage.flowStartingPoints = [{ nodeId: start.id, name: "Start" }];
  }
  for (const l of dis.lossy || []) {
    warnings.push(`lossy · ${l.screen}: ${l.kind} — ${l.note || "see figma-mapping.md"}`);
  }

  figma.viewport.scrollAndZoomIntoView(Object.values(frameById));
  figma.notify(`Built ${dis.screens.length} screens, ${dis.flow.transitions.length} edges`);
  figma.ui.postMessage({ type: "done", warnings });
}

/* ---------- entry ---------- */
figma.showUI(__html__, { width: 360, height: 280 });
figma.ui.onmessage = async (msg: { type: string; dis?: string }) => {
  if (msg.type === "build" && msg.dis) {
    try {
      await build(JSON.parse(msg.dis) as DIS);
    } catch (e) {
      figma.ui.postMessage({ type: "error", message: String(e) });
    }
  }
};
