# The Design Interaction Spec (DIS)

DIS is a small JSON contract that sits between two worlds that don't speak the
same language:

- **Generated UI** — what Claude Design (or any code-gen) produces: a running
  web app where interactions are *runtime* JavaScript.
- **Figma prototypes** — where interactions are a *declarative*, fixed set of
  trigger → action → destination edges plus Smart Animate.

These two are not the same expressive power. The web is Turing-complete at
runtime; Figma's prototype model is a constrained subset. So a faithful 1:1
import of "all interactions" is impossible in principle, not just hard. Existing
HTML→Figma tools sidestep this by importing a single flattened page — and in
doing so they throw away the one thing a prototype is *about*: how screens
connect.

DIS fixes the target. Instead of trying to recover intent from compiled,
interaction-stripped HTML, it captures the **state machine** and **token
system** as first-class data, and marks whatever Figma genuinely cannot run as
explicitly `lossy` rather than silently dropping it.

The same document is read from both directions:

- **Generation end** emits DIS-conformant structure (see the generation rules in
  `SKILL.md`). The spec is the source of truth; the HTML/JSX is one rendering.
- **Conversion end** parses an export *into* DIS (`scripts/extract_ir.py`), then
  a Figma consumer maps DIS onto Variables, components, frames, and Reactions
  (see `references/figma-mapping.md`).

## Shape

```
version      string
meta         { name, source, tokenNamespace, persona? }
tokens       { color{}, typography{}, radius{}, spacing{} }   name -> value
components   [ { id, kind?, variants?, source? } ]
screens      [ { id, label, step, component, frame } ]        frame=null until render pass
flow         { initial, transitions[] }
lossy        [ { screen, kind, note } ]
```

A transition edge is the unit that carries interaction:

```json
{
  "from": "done",
  "trigger": "onClick",
  "intent": "restart",
  "element": "onRestart",
  "to": "welcome",
  "animation": "smartAnimate",
  "sideEffects": ["resetState"]
}
```

`intent` exists so the Figma side can choose sensible defaults: an `advance`
edge gets a push/Smart Animate left-to-right, a `back` edge the reverse, a
`branch` opens an alternate path. `sideEffects` (like a state reset on restart)
can't run in Figma — recording it keeps the dev handoff honest instead of
pretending the prototype is the product.

## Design rules

1. **Screens are states, not pages.** One DIS screen = one Figma frame = one
   addressable state of the UI. A single code file with `view` state that swaps
   components produces *many* DIS screens, one per reachable value.

2. **`element` must be a stable name.** Smart Animate binds layers across frames
   by name. The triggering element's `element` id has to resolve to a node whose
   name is identical in source and destination frames, or the transition will
   hard-cut instead of animating.

3. **Geometry is a separate pass.** Token + flow extraction is deterministic and
   needs no browser (the structure lives in the source). Per-screen frame
   geometry does need a render — see `figma-mapping.md`. Until then `frame` is
   `null`, and the IR is still complete enough to build the prototype graph.

4. **Lossy is loud.** Anything Figma can't run — JS-timed sequences, progress
   animations, conditional logic beyond a single variable — goes in `lossy` with
   a short note on the best available degradation. Never drop it quietly.

## Validate

```bash
python -c "import json,jsonschema,sys; \
  jsonschema.validate(json.load(open('examples/wellcee/wellcee.ir.json')), \
  json.load(open('schema/interaction-spec.schema.json')))" && echo OK
```
