# Mapping DIS onto Figma

This is the consumer side of the contract: how a Figma plugin turns a Design
Interaction Spec into a real, clickable prototype. Run it inside a Figma plugin
(the `figma.*` API is only available there).

## 1. Tokens → Variables

`tokens.color` becomes a Variables collection of `COLOR` variables; `radius` and
`spacing` become `FLOAT` variables; `typography` becomes text styles. Naming the
variables after the token keys keeps the design system legible and lets you
rebind later.

```js
const col = figma.variables.createVariableCollection("tokens/color");
const mode = col.modes[0].modeId;
for (const [name, hex] of Object.entries(ir.tokens.color)) {
  const v = figma.variables.createVariable(name, col, "COLOR");
  v.setValueForMode(mode, hexToRgb(hex));  // {r,g,b} in 0..1
}
```

## 2. Components → Figma components

Each `components[]` atom (Chip, PillButton, Card, Ring, …) becomes a Figma
component. Where the source declares variant states (selected / ai / disabled),
model them as Figma **variant properties** so a single component covers all
states — this is what lets a `Change to` interaction swap states later.

## 3. Screens → frames

One frame per `screens[]` entry, named by screen `id`. Frame geometry comes from
the **render pass** (section 5). Critically: name the layers consistently across
frames. The shared `Welly` avatar, the bottom CTA, the step pills — if they
carry the same node name in every frame they appear in, Smart Animate
interpolates them; if not, every transition hard-cuts.

## 4. Flow → Reactions (the part flat converters skip)

This is the whole point. Each `flow.transitions[]` edge becomes a Reaction on
the source frame's triggering node. Figma applies reactions via
`node.setReactionsAsync(...)`.

```js
const ANIM = {
  smartAnimate: { type: "SMART_ANIMATE", easing: { type: "EASE_OUT" }, duration: 0.3 },
  dissolve:     { type: "DISSOLVE",      easing: { type: "EASE_OUT" }, duration: 0.3 },
  instant:      null,
};

// intent → a sensible directional default when the edge doesn't override it
const TRIGGER = { onClick: { type: "ON_CLICK" } };

async function wireFlow(ir, frameById, nodeForElement) {
  for (const t of ir.flow.transitions) {
    const sourceFrame = frameById[t.from];
    const destFrame   = frameById[t.to];
    // the node the user taps; falls back to the whole frame if unresolved
    const trigger = nodeForElement(t.from, t.element) || sourceFrame;

    const reaction = {
      trigger: TRIGGER[t.trigger] || { type: "ON_CLICK" },
      action: {
        type: "NODE",
        destinationId: destFrame.id,
        navigation: "NAVIGATE",
        transition: ANIM[t.animation] ?? ANIM.smartAnimate,
        preserveScrollPosition: false,
      },
    };
    const existing = await trigger.getReactionsAsync?.() ?? trigger.reactions ?? [];
    await trigger.setReactionsAsync([...existing, reaction]);
  }
  // start frame
  // (set the page's flow starting point to frameById[ir.flow.initial])
}
```

Notes:
- `intent` lets you pick direction without per-edge config: `advance` → push
  left, `back` → push right, `branch` → dissolve/overlay, `restart` → Smart
  Animate back to `initial`.
- `sideEffects` (e.g. `resetState`) have **no Figma equivalent**. Leave a comment
  on the frame or surface them in the dev-handoff notes; do not pretend the
  prototype clears state.
- A `branch` to a modal-like screen is often better as `Open Overlay` than a
  full navigate — decide per project.

## 5. The render pass (filling `frame`)

Token + flow extraction is static and browser-free. Geometry is not: you have to
run the UI. The cleanest source is the export's runnable bundle
(`*.bundle.html` / the offline HTML), driven headlessly:

1. Load the bundle in Playwright/Puppeteer.
2. For each screen, drive the app into that state (set the `view`, or click
   through the recovered transitions) and let it settle.
3. Walk the DOM, read `getBoundingClientRect()` + `getComputedStyle()` for each
   element, and emit a layout tree into `screens[].frame.nodes`, **assigning the
   stable layer names from rule 3**.
4. The Figma plugin builds frames from that tree (flexbox/grid → auto-layout).

Keeping this pass separate means the interaction graph — the hard, novel part —
is recoverable even before any pixels are placed.

## What does not survive (by design)

| Source behavior | Figma result |
| --- | --- |
| Screen → screen navigation | ✅ Reaction + Smart Animate |
| Hover / pressed / selected states | ✅ variants + `Change to` / While Hovering |
| Modal / dropdown / sheet | ✅ Open / Swap / Close Overlay |
| Frame-to-frame shared-element motion | ✅ Smart Animate (needs matching layer names) |
| JS-timed sequences (typing, autoplay) | ⚠️ end-state, or a 2-frame Smart Animate |
| Continuous progress animation (ring fill) | ⚠️ bake start/end frames |
| Arbitrary state logic beyond one variable | ❌ record in `lossy` / dev handoff |

The `⚠️`/`❌` rows are Figma's ceiling, not a bug in the bridge. Surfacing them in
`lossy` is the honest version of what flat converters do silently when they emit
one frozen page.
