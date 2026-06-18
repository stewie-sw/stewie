# STEWIE Design System (seed)

The extracted, standardized, **reusable** design system for the STEWIE cockpit: tokens, self-hosted
fonts, an SVG icon set, and the core React components. It is built from the deployed cockpit's **real**
brand (the `:root` in `stewie/server/index.html`), not invented.

It exists for three reasons at once:

1. **Standardize the design language** (tokens + type/spacing scale + icon set + one component vocabulary),
   closing the gaps the inline cockpit styling had (leaked hex literals, no spacing/type scale, emoji icons).
2. **See it rendered before the migration** — `dist/stewie-ds.{js,css}` is what `/design-sync` uploads to
   claude.ai/design so new cockpit UI can be designed with the real components.
3. **Seed the front-end rewrite's component library** (the first brick; the view models in
   `stewie/server/web/assets/adapters.js` become these components' typed props).

## What's in it

| Layer | File(s) | Notes |
|---|---|---|
| Tokens | `src/tokens.css` | color (verbatim from the deployed dark + light themes), type scale, spacing (8px base), radius, elevation. The brand: lunar black + graphite ramp, ONE hot accent = drum red. |
| Fonts | `src/fonts/*.woff2` | **Orbitron** (display: chrome, tabs, headings, metric values) + **Inter** (body/controls), self-hosted, no CDN. |
| Icons | `src/Icon.tsx` | one `<Icon name=… />`, currentColor SVG, replaces the cockpit's emoji glyphs (🔔 ▦ ▸ ⤓ ⦿ …). |
| Components | `src/components/*.tsx` | `ModeBar` (§5 truth-boundary selector), `SourceToggle` (PO-10 provenance layers), `WorkAreaTabs` (§11 FS-03), `Panel`, `Button`, `MetricTile`, `SubsystemChip`. |
| Stylesheet | `src/styles.css` | `@import`s tokens + `@font-face` + every `ds-*` component class. Rendered designs receive this file's transitive `@import` closure. |

## Two safety invariants the components encode

- **Mode is the truth boundary** (`ModeBar`, PRD §5): `GIS-PLAN / TRAIN / SIM-OPERATE / EVALUATE / OPERATE`,
  role-gated; `OPERATE` is the only mode that commands real hardware.
- **No truth on real hardware** (`SourceToggle`, PO-10): the `truth` provenance layer is **disabled in
  OPERATE** — belief can never masquerade as truth on a real rover. `truthAvailable(mode)` is the predicate;
  it is unit-tested and verified in the rendered DOM (`gallery/render.py`).

## Styling idiom

Utility is **not** the idiom — components own their styles via the `ds-*` class vocabulary, and **all**
color/spacing comes from the tokens in `src/tokens.css` (never raw literals). To restyle, edit a token.
State is a `data-*` or `aria-*` attribute (`aria-pressed`, `aria-selected`, `data-src`, `data-operate`).

## Build / test / render

```sh
npm install
npm run build        # esbuild -> dist/stewie-ds.js (window.StewieDS) + dist/stewie-ds.css + fonts + dist/gallery.js
npm test             # vitest: 12 tests, incl. the role-gating + truth-disabled-in-OPERATE invariants
node_modules/.bin/tsc --noEmit   # type soundness (esbuild does not type-check)
# render the gallery for visual review (real headless Chromium, swiftshader):
<repo>/.venv/bin/python gallery/render.py   # -> validation/gallery_sim_operate.png + gallery_operate.png
```

`gallery/` (the showcase app + `render.py`) and `validation/` (screenshots) are the **review/verification
harness** — not shipped. `dist/stewie-ds.{js,css}` + `src/` are the design system.

## Not done here (the gated next step)

The actual upload to claude.ai/design via `/design-sync` is an **outward action** and is **not** performed
automatically — it needs Aaron's explicit go (a first sync creates a cloud project and can take a while).
