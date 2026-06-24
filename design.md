---
version: alpha
name: STEWIE Cockpit
description: >
  Visual identity for the STEWIE mission-planning cockpit: a dark, mission-control
  HUD for authoring and releasing lunar surface-construction plans. Technical,
  high-contrast, telemetry-dense. Orbitron for labels and chrome, system-ui for
  reading, a single crimson accent reserved for state and action. Dark is the
  default surface; a light theme mirrors every token.
colors:
  # --- dark theme (default) ---
  bg: "#0a0a0c"            # app background
  panel: "#101013"         # panel / card surface
  head: "#1b1b1f"          # header top stop (gradient to #101013)
  line: "#26262c"          # hairline borders / dividers
  field: "#141417"         # input / control surface
  fieldBorder: "#34343c"   # input border
  text: "#d6d6da"          # primary text
  muted: "#8a8a93"         # secondary text / labels
  dim: "#86868f"           # tertiary text (>= 4.5:1 on panel/field)
  accent: "#ef3a52"        # state + focus + active (>= 4.5:1 as text on panel/field)
  fill: "#c8102e"          # primary action fill
  fillHover: "#a30d26"     # primary action fill, hover
  # --- light theme (alt; same token names) ---
  light.bg: "#f4f6fa"
  light.panel: "#ffffff"
  light.head: "#e8edf5"
  light.line: "#c9d4e4"
  light.field: "#eef2f8"
  light.fieldBorder: "#b8c6dc"
  light.text: "#16202e"
  light.muted: "#51607a"
  light.dim: "#5a6680"
  light.accent: "#1a5fd0"
  light.fill: "#2563eb"
  light.fillHover: "#1d4ed8"
typography:
  display:
    fontFamily: "Orbitron, system-ui, sans-serif"   # vendored OFL, no CDN
    fontWeight: 700
    letterSpacing: "0.08em"                          # 0.08em chrome, up to 0.14em on section heads
    textTransform: uppercase
  heading:
    fontFamily: "Orbitron, system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 800
    letterSpacing: "0.08em"
  body:
    fontFamily: "system-ui, sans-serif"
    fontSize: "13px"                                 # --fontpx, operator-adjustable, persisted
    fontWeight: 400
    lineHeight: 1.45
  caption:
    fontFamily: "system-ui, sans-serif"
    fontSize: "11px"
  label:
    fontFamily: "Orbitron, system-ui, sans-serif"
    fontSize: "10px"
    fontWeight: 700
    letterSpacing: "0.12em"
    textTransform: uppercase
  numeric:
    fontFeature: "tabular-nums"                      # telemetry / counts align in columns
rounded:
  sm: "6px"      # fields, toolbars, small controls
  md: "8px"      # buttons, badges
  lg: "12px"     # modals, floating panels
  tabTop: "7px 7px 0 0"   # top-tab top corners only
spacing:
  xs: "2px"
  sm: "4px"
  md: "6px"
  base: "8px"    # the default unit
  lg: "10px"
  xl: "12px"
components:
  tab:                         # .vtab — top navigation tab
    backgroundColor: "field"
    textColor: "muted"
    typography: "label"
    rounded: "tabTop"
    padding: "0 12px"
    active: { backgroundColor: "bg", textColor: "accent", borderColor: "fieldBorder" }
  buttonPrimary:               # button.fill — commit / release / run
    backgroundColor: "fill"
    textColor: "#ffffff"
    borderColor: "fillHover"
    rounded: "md"
    fontWeight: 600
  buttonSecondary:             # button.site — passive / navigational
    backgroundColor: "transparent"
    textColor: "text"
    borderColor: "fieldBorder"
    rounded: "md"
    hover: { borderColor: "accent", textColor: "accent" }
  panel:                       # .pane / #panel — sidebar + work-area surfaces
    backgroundColor: "panel"
    borderColor: "line"
    rounded: "lg"
  sectionHeader:               # .ctxh / #panel h3 — pane + group headers
    typography: "label"
    textColor: "text"
  stepperStep:                 # #stepper .step — the ConOps mission spine
    typography: "label"
    textColor: "dim"
    done: { dotColor: "accent" }
    current: { dotColor: "text", glow: "0 0 0 3px rgba(232,57,82,0.30)" }
---

## Overview

STEWIE is a lunar surface-construction mission planner. The cockpit is where an operator
sites a worksite on a real DEM, drops structures, rehearses, validates, and releases a plan.
The identity is **mission control, not consumer app**: a near-black instrument panel that
keeps attention on the map and the numbers, with chrome that recedes until it carries state.

Three rules drive every choice:

1. **The surface recedes; state advances.** Backgrounds are near-black neutrals. The single
   crimson accent is *earned*: it marks the active tab, a focused control, a ready/blocked
   state, a primary action. Color is information, not decoration.
2. **Two voices.** Orbitron (uppercase, letter-spaced) is the instrument voice for chrome,
   tabs, section labels, and the mission stepper. system-ui is the reading voice for prose,
   values, and dense content. Never set body copy in Orbitron; never label a control in system-ui.
3. **Density with air.** This is a data-dense tool. Spacing is tight (8px base) but consistent,
   and numbers use tabular figures so telemetry columns line up.

The cockpit ships **dark by default**. A light theme mirrors every token one-to-one for bright
rooms and projection; nothing is dark-only.

## Colors

The palette is one neutral ramp plus one accent.

- **Neutrals (dark):** `bg #0a0a0c` (app) sits behind `panel #101013` (cards), separated by the
  `line #26262c` hairline. Controls sit on `field #141417` inside a `fieldBorder #34343c`. Header
  bars use a subtle vertical gradient from `head #1b1b1f` down to the panel.
- **Text ramp:** `text #d6d6da` for primary, `muted #8a8a93` for labels and secondary, `dim
  #86868f` for tertiary. Every ramp step is verified at or above WCAG 4.5:1 on its intended
  surface (there is a contrast test gating this; see Do's and Don'ts).
- **Accent + action:** `accent #ef3a52` is the one expressive color, used for active state, focus
  rings, readiness dots, and emphasis. Primary actions fill with `fill #c8102e`, darkening to
  `fillHover #a30d26` on hover. The accent doubles as a focus glow at 30 percent alpha.
- **Light theme** swaps to a cool blue accent (`#1a5fd0` / fill `#2563eb`) on near-white panels;
  the token *names* and *roles* are identical, so components are written once.

Do not introduce a second hue. Status that is not "accent" is communicated with the neutral ramp
plus iconography, not a new color, unless a semantic palette (success/warn/error) is added to the
tokens first.

## Typography

- **Display / chrome / labels: Orbitron**, vendored under the OFL (no CDN dependency). Always
  uppercase, weight 700 to 800, letter-spacing 0.08em for chrome and tabs, widening to 0.12 to
  0.14em for small section labels. This is the geometric, technical voice of the instrument panel.
- **Body / values / prose: system-ui, sans-serif**, base 13px at line-height 1.45. The base size
  is operator-adjustable (the `--fontpx` token) and persists per operator.
- **Type scale (px):** 9 micro, 10 label, 11 caption, 12 secondary, **13 body (base)**, 14 heading,
  with 17 to 18 reserved for icon glyphs. Prefer an existing step over a new size.
- **Numbers:** telemetry, counts, and money use `tabular-nums` so columns align as values change.

## Layout

- **Unit:** 8px base. The spacing scale is 2 / 4 / 6 / 8 / 10 / 12; pick a scale step rather than
  an arbitrary value.
- **Frame:** a vertical app shell, top to bottom: a thin **stepper** (the ConOps mission spine,
  34px tall), a **tab strip**, then a two-column work area of a fixed **left sidebar** (panel
  surface, right hairline border) and a flexible **work pane**. Panes own their own caption row.
- **Scrolling:** the shell does not scroll; panes and the sidebar scroll internally. The stepper
  scrolls horizontally on narrow viewports rather than wrapping.
- **Customization is view-only.** Operators may drag-reorder tabs and sidebar panes and adjust
  font size; these are per-operator view preferences (localStorage) and never change command
  authority, access tier, or contracts (the FS-21 invariant).

## Elevation & Depth

Depth is sparing and always dark; there are no light/raised surfaces in the dark theme.

- **Focus / active glow:** `0 0 0 3px rgba(232,57,82,0.30)` — the accent ring on the current
  stepper node and focused controls.
- **Attention pulse:** an animated ring from `0 0 0 0` to `0 0 0 16px` of fading accent, for a
  one-shot "look here" only (never a persistent loop).
- **Floating panels (drawers):** `4px 0 24px rgba(0,0,0,0.6)` cast from the panel edge.
- **Modals / popovers:** `0 18px 60px rgba(0,0,0,0.6)`; lighter toasts use `0 10px 40px`.

Resting surfaces (panels, fields, tabs) carry **no** shadow; they are separated by the hairline
`line` border. Shadow means "this floats above the panel," nothing else.

## Shapes

- **Radius scale:** `sm 6px` (fields, toolbars, small controls), `md 8px` (buttons, badges),
  `lg 12px` (modals, floating panels). Tabs round only their **top** corners (`7px 7px 0 0`) so
  they read as attached to the pane below.
- Borders are 1px hairlines in `line` (or `fieldBorder` on controls). Outlines on focus are 2px in
  `accent` with a 1px offset.
- Geometry is rectilinear and instrument-like; avoid pill shapes and large radii.

## Components

- **Top tab (`.vtab`):** the primary navigation. Rests on `field` with `muted` Orbitron label;
  **active** lifts to the `bg` color with an `accent` label and a `fieldBorder` edge, visually
  continuous with the pane. A small readiness dot may trail the label in `dim`.
- **Primary button (`button.fill`):** crimson `fill` background, `fillHover` border, white label,
  weight 600. Reserved for the committing action in a pane (run, release, add to queue).
- **Secondary button (`button.site`):** transparent with a `fieldBorder` edge and `text` label;
  on hover the edge and label go `accent`. For passive and navigational actions.
- **Panel / pane:** `panel` surface, `line` border, `lg` radius. The sidebar is a fixed-width
  panel with a right hairline; work panes flex.
- **Section header (`.ctxh`, `#panel h3`):** uppercase Orbitron label in `text` (group head) or
  `muted` (sub-group), wide letter-spacing.
- **Mission stepper (`#stepper .step`):** the ConOps spine. Steps are `dim` Orbitron micro-labels
  with a dot; a **done** step fills its dot `accent`; the **current** step fills its dot `text`
  and wears the accent focus glow. Steps are joined by a right-arrow glyph.

## Do's and Don'ts

**Do**

- Reserve `accent` for state, focus, and the one primary action per context.
- Label controls and chrome in uppercase Orbitron; set prose and values in system-ui.
- Use `tabular-nums` for every changing number.
- Snap spacing to the 8px scale and radius to 6 / 8 / 12.
- Keep new color choices inside the existing tokens; mirror any new token in **both** themes.
- Treat tab/pane reordering and font size as per-operator view preferences only.

**Don't**

- Don't add a second accent hue or set body text in Orbitron.
- Don't put shadows on resting surfaces; shadow is reserved for floating layers.
- Don't ship a token at a contrast below WCAG 4.5:1 on its surface. The cockpit has an automated
  contrast test (`stewie/server/web/assets/a11y_contrast.test.js`); a failing token fails CI.
- Don't make a customization control change auth, access tier, or a contract (FS-21 view-only).
- Don't introduce large radii or pill shapes; the cockpit is rectilinear and instrument-like.
