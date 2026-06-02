# claude-design-figma-bridge

Carry **interactions**, not just pixels, from generated UI into Figma.

**English** | [中文](#中文)

---

## The problem

HTML→Figma tools (Anima, html.to.design, …) import a single flattened page. They
drop the animations, the clicks, and — most importantly — the **flow between
screens**. That happens because the export they read is compiled,
interaction-stripped HTML: by the time the page exists, the *intent* behind every
interaction has been baked into runtime JavaScript and is gone.

The deeper reason a better parser can't fully fix it: the web is Turing-complete
at runtime, while Figma's prototype model is a small declarative subset (trigger
→ action → destination, plus Smart Animate). A 1:1 import of "all interactions"
is impossible *in principle*. So the right move isn't a smarter scraper — it's a
**contract** that captures the part that does map, and is honest about the part
that doesn't.

## The idea

This repo defines the **Design Interaction Spec (DIS)** — a small JSON
interchange format between generated UI and Figma prototypes — and tooling that
works in both directions.

```
                 ┌──────────── DIS (the contract) ─────────────┐
 generation end  │  tokens · components · screens · flow · lossy │  conversion end
   (rules) ──────▶                                               ◀────── (scripts)
                 └───────────────────────────────────────────────┘
                                      │
                                      ▼
                        Figma: Variables · components ·
                        frames · Reactions (Smart Animate)
```

- **Generation end** — rules that steer a generating model (Claude Design /
  Claude Code) to emit DIS-shaped output so it imports cleanly later.
- **Conversion end** — two passes:
  - `scripts/extract_ir.py` recovers tokens + the full state machine
    **statically, no browser** (the structure lives in the `.jsx` source).
  - `scripts/render_frames.py` runs each screen in headless Chromium to fill
    per-screen geometry.
- **Figma consumer** — `figma-plugin/` reads a DIS and builds the prototype:
  token Variables, one frame per screen, and a Reaction per flow edge.

## Pipeline

```bash
# 1. export → DIS (flow + tokens, deterministic)
python scripts/extract_ir.py path/to/export -o out.ir.json --name "My project"

# 2. fill geometry (needs the browser binary once)
pip install playwright && playwright install chromium
python scripts/render_frames.py path/to/export out.ir.json

# 3. validate
python -c "import json,jsonschema; jsonschema.validate(\
  json.load(open('out.ir.json')), \
  json.load(open('schema/interaction-spec.schema.json')))" && echo OK

# 4. build the Figma plugin, then paste out.ir.json into its UI
cd figma-plugin && npm install && npm run build
```

## Worked example

`examples/wellcee/wellcee.ir.json` is real output from a multi-screen Claude
Design prototype. The flat export was 6 disconnected pages with no transitions;
`extract_ir.py` recovered the whole graph:

```
welcome --onStart(advance)--> chat        welcome --onManual(branch)--> manual
chat    --onComplete(advance)--> intro     chat    --onManual(branch)--> manual
manual  --onBack(back)--> welcome          manual  --onNext(advance)--> tags
manual  --onAskWelly(branch)--> chat
intro   --onBack(back)--> chat             intro --onNext(advance)--> tags
tags    --onBack(back)--> intro            tags  --onNext(advance)--> rent
rent    --onBack(back)--> tags             rent  --onNext(advance)--> done
done    --onBack(back)--> rent             done  --onRestart(restart)--> welcome  + resetState
```

15 edges, 7 screens, intents and side effects intact — the layer flat
converters throw away.

## Layout

```
SKILL.md                              the skill (both ends)
schema/interaction-spec.schema.json   machine-checkable contract
references/ir-contract.md             the contract, explained
references/figma-mapping.md           DIS → Figma Variables / components / Reactions
scripts/extract_ir.py                 conversion: export → DIS (flow + tokens)
scripts/render_frames.py              conversion: fill per-screen geometry (Playwright)
figma-plugin/                         consumer: DIS → Figma prototype (TypeScript)
examples/wellcee/wellcee.ir.json      validated real-world output
```

## Status

`v0.1`. Flow + token extraction implemented and validated on a real project. The
Figma plugin typechecks against the official Figma API typings and builds. The
render pass is implemented; it needs a local `playwright install chromium`.

---

# 中文

把**交互**——而不只是像素——从生成式 UI 带进 Figma。

[English](#claude-design-figma-bridge) | **中文**

## 问题

现有的 HTML→Figma 工具(Anima、html.to.design 等)只能导入一张扁平的页面,会丢掉
动画、点击,以及最关键的**屏与屏之间的流程**。原因在于它们读的是已经编译、交互被
剥离后的 HTML:页面生成出来的那一刻,每个交互背后的*意图*都已经被烤进运行时
JavaScript 里,消失了。

更深一层:再好的解析器也补不全,因为网页在运行时是图灵完备的,而 Figma 的原型模型
是一个很小的声明式子集(触发器 → 动作 → 目标,外加 Smart Animate)。把“全部交互”
做 1:1 导入在原理上就不可能。所以正确的做法不是更聪明的爬虫,而是一份**契约**:
抓住能映射的部分,并对映射不了的部分保持诚实。

## 思路

本仓库定义了 **Design Interaction Spec(DIS)**——生成式 UI 与 Figma 原型之间的
一份小型 JSON 交换格式——以及围绕它双向工作的工具。

- **生成端**:用规则引导生成模型(Claude Design / Claude Code)产出 DIS 形状的
  输出,使其日后能干净地导入。
- **转换端**:两遍处理。
  - `scripts/extract_ir.py` **静态、不需浏览器**地还原 token 和完整状态机
    (结构就在 `.jsx` 源码里)。
  - `scripts/render_frames.py` 在无头 Chromium 里渲染每一屏,补上几何信息。
- **Figma 消费端**:`figma-plugin/` 读入 DIS,搭出原型——token 变量、一屏一帧、
  每条流程边一个 Reaction。

## 流程

```bash
# 1. 导出 → DIS(流程 + token,确定性)
python scripts/extract_ir.py 导出目录 -o out.ir.json --name "项目名"

# 2. 补几何(首次需要下载浏览器内核)
pip install playwright && playwright install chromium
python scripts/render_frames.py 导出目录 out.ir.json

# 3. 校验
python -c "import json,jsonschema; jsonschema.validate(\
  json.load(open('out.ir.json')), \
  json.load(open('schema/interaction-spec.schema.json')))" && echo OK

# 4. 编译 Figma 插件,把 out.ir.json 粘进插件 UI
cd figma-plugin && npm install && npm run build
```

## 真实样例

`examples/wellcee/wellcee.ir.json` 是从一个多屏 Claude Design 原型导出的真实结果。
扁平导出是 6 张互不相连、没有任何转场的页面;`extract_ir.py` 把整张图都还原了:
15 条边、7 个屏,连每条边的意图和 `done → welcome` 的 `resetState` 副作用都在——
正是扁平转换器丢掉的那一层。

## 状态

`v0.1`。流程 + token 抽取已实现并在真实项目上验证;Figma 插件已对官方 Figma API
类型通过检查并能编译;render pass 已实现,本地需先 `playwright install chromium`。

## 设计文档

- 契约本身:`references/ir-contract.md`
- DIS → Figma 的映射与有损降级:`references/figma-mapping.md`
- 两端规则:`SKILL.md`
