---
name: claude-design-figma-bridge
description: >-
  Carry interactions, not just pixels, between generated UI and Figma. Use this
  skill whenever the user is moving a Claude Design project (or any generated
  web UI) into Figma, building or designing a Figma plugin that imports
  prototypes, or complaining that html-to-figma tools (Anima, html.to.design)
  only import a single static page and drop the animations / clicks / screen
  flow. It defines a small JSON contract (the Design Interaction Spec) that
  captures the screen-to-screen state machine and design tokens, and works both
  ways: it tells a generating Claude how to emit Figma-importable structure, and
  it parses an existing Claude Design export into that contract. Reach for it on
  any mention of Claude Design exports, Claude Code handoff bundles, Figma
  prototype import, design-to-Figma handoff, or preserving interactivity when
  converting UI to Figma — even if the user hasn't named the contract.
---

# Claude Design ↔ Figma bridge

Flat HTML→Figma converters import one frozen page because the export they read
has already compiled interaction *intent* into runtime JS. This skill works
against a shared contract instead — the **Design Interaction Spec (DIS)** — so
the screen flow and tokens survive in both directions.

Read `references/ir-contract.md` first; it is the source of truth for the JSON
shape. The two ends below both revolve around it.

## Which end am I on?

- The user has a **Claude Design export / handoff zip** and wants it in Figma →
  **conversion end** (run the extractor, then map to Figma).
- The user is **generating new UI** and wants it to import cleanly later →
  **generation end** (steer the output so it's DIS-shaped).
- Building the **Figma plugin / contract itself** → read all of
  `references/` and treat DIS as the interface both sides target.

## Conversion end — export → DIS

The structure lives in the `.jsx` source of the export (the token module + the
router with its state switch), not in the flattened HTML. Extract it
deterministically — no browser needed:

```bash
python scripts/extract_ir.py <export_dir> -o out.ir.json --name "Project name"
```

This recovers tokens, the component inventory, every screen, and the full
transition graph (with each edge's intent and side effects). It leaves
`screens[].frame = null` — per-screen geometry is a separate render pass:

```bash
pip install playwright && playwright install chromium
python scripts/render_frames.py <export_dir> out.ir.json
```

`render_frames.py` loads each screen's standalone HTML (`figma-screens/*.html`)
in headless Chromium and fills `screens[].frame` with positioned, styled nodes.
The two halves of the export map to the two halves of the IR: `app.jsx` gives
the flow, `figma-screens/` gives the geometry.

Then feed the DIS into the consumer in `figma-plugin/` (paste it into the
plugin UI), which builds Variables, frames, and a Reaction per edge per
`references/figma-mapping.md`. Build the plugin with `cd figma-plugin && npm
install && npm run build`.

If the export's source files differ from the expected shape (no token object, or
no `view`-switch router), say so and inspect the files before forcing the
parser — the regexes assume a single-`view` state machine.

## Generation end — emit DIS-shaped UI

When generating a prototype the user intends to hand to Figma, the goal is that
`extract_ir.py` can read it back losslessly. Produce output that obeys these
rules, and explain *why* to the user so they can keep it consistent later:

1. **One token module.** Put every color, font, radius, and spacing value in a
   single namespaced object (e.g. `const WC = { teal: '#26BCBB', ... }`). No
   hex codes scattered through components — scattered values can't become Figma
   Variables.
2. **One explicit state machine.** Drive navigation through a single `view`
   state and one `go(target)` function. Declare the screens in an explicit
   array (`FLOW = [{id,label}, ...]`). Never navigate by ad-hoc conditionals
   spread across components — the flow has to be readable in one place.
3. **One component per screen**, plus reusable atoms (button, chip, card). This
   maps 1:1 to Figma frames + components.
4. **Stable element names.** Give shared elements (avatar, bottom CTA, header)
   the same identifier wherever they appear, so Smart Animate can bind them.
5. **Spec is the source of truth.** If asked, emit the DIS JSON alongside the
   code and treat the rendered UI as a view of it — never produce a spec and
   code that can drift apart.

Minimal conformant skeleton:

```jsx
const FLOW = [{ id:'welcome', label:'Welcome' }, { id:'next', label:'Next' }];
function App() {
  const [view, setView] = React.useState('welcome');
  const go = setView;
  if (view==='welcome') return <Welcome onStart={()=>go('next')} />;
  if (view==='next')    return <Next onBack={()=>go('welcome')} />;
}
```

## Validate output

DIS files should validate against `schema/interaction-spec.schema.json`. A
worked example produced from a real Claude Design project lives at
`examples/wellcee/wellcee.ir.json` — use it as the reference for what good
output looks like.
