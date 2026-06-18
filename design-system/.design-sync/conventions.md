# Building with the STEWIE design system

STEWIE is a lunar mission-planning + simulation cockpit. The look is **lunar black + graphite, one hot
accent = drum red**, display type in **Orbitron** (caps, tracked), body in **Inter**. Build dense,
operator-grade UI; reserve the red accent for the active/primary/danger affordance, never as decoration.

## Wrapping and setup

- Put **`className="ds-root"`** on a top-level wrapper (or `<body>`). It sets the base font, background,
  and text color; the design tokens live on `:root` so they apply globally. There is **no React provider
  or context** to wire — components are self-contained.
- The cockpit defaults to the **dark** theme. For light, add **`className="light"`** to a wrapper (it
  re-binds the same token names).
- Styling ships in **`styles.css`** (its `@import` closure carries tokens, `@font-face`, and component CSS).

## The styling idiom — tokens, never literals

This is a **token + `ds-`-class** system, not utilities and not inline styles. Every color and spacing
value comes from a CSS variable in `tokens.css`. To style your own layout glue, use these — do not invent
hex values:

- **Surfaces**: `--bg` `--panel` `--head` `--line` `--field` `--field-bd`
- **Text**: `--txt` `--muted` `--dim`
- **Accent (drum red)**: `--accent` `--fill` `--fill-h`
- **Status**: `--ok` `--warn` `--danger`
- **Spacing (8px base)**: `--sp-1`(4) `--sp-2`(8) `--sp-3`(12) `--sp-4`(16) `--sp-5`(24) `--sp-6`(32)
- **Type/fonts**: `--font-display` (Orbitron) `--font-body` (Inter) `--fs-cap` `--fs-sm` `--fs-body` `--fs-lg` `--fs-xl` `--ls-display`
- **Radius/elevation**: `--r-sm` `--r-md` `--r-lg` `--focus-ring`

Component state is expressed with `aria-*` / `data-*` (`aria-pressed`, `aria-selected`, `data-src`,
`data-operate`), not extra classes.

## Two invariants you must preserve

STEWIE commands real hardware, so two rules are load-bearing, not cosmetic:

- **Mode is the truth boundary** (`ModeBar`): `GIS-PLAN / TRAIN / SIM-OPERATE / EVALUATE / OPERATE`,
  role-gated. Only `OPERATE` reaches real hardware. Always show the active mode.
- **No truth on real hardware** (`SourceToggle`): the `truth` provenance layer must be **disabled in
  OPERATE**. Use `truthAvailable(mode)` — never present belief as truth on a live rover.

## Components

`ModeBar`, `SourceToggle`, `WorkAreaTabs`, `Panel`, `Button`, `MetricTile`, `SubsystemChip`, and `Icon`
(one `<Icon name=… />`, currentColor SVG; use it instead of emoji). Read each component's `.d.ts` for its
props and its `.prompt.md` for usage. Read `styles.css` before adding any styling of your own.

## One idiomatic snippet

```tsx
<div className="ds-root" style={{ padding: "var(--sp-5)" }}>
  <div style={{ display: "flex", gap: "var(--sp-5)", alignItems: "center" }}>
    <ModeBar mode="SIM-OPERATE" roleRank={3} onChange={setMode} />
    <SourceToggle mode={mode} active={["forecast", "truth", "belief"]} onToggle={toggle} />
  </div>
  <WorkAreaTabs active="plan" onSelect={setArea} />
  <Panel title="Physics" subsystem="FORGE">
    <MetricTile label="Drum fill" value={74} unit="%" status="ok" />
  </Panel>
</div>
```
