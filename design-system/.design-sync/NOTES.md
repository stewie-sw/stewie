# design-sync notes — STEWIE Design System

Repo-specific gotchas a future sync should know.

- **Build**: `npm run build` = esbuild (`build.mjs`: IIFE `dist/stewie-ds.js`, ESM `dist/index.js`, CSS
  `dist/stewie-ds.css`, fonts) + `tsc -p tsconfig.build.json` (emits `dist/types/*.d.ts`). The converter
  consumes `--entry ./dist/index.js`; the `.d.ts` tree at `dist/types` is what prop extraction reads.
- **cssEntry** = `dist/stewie-ds.css` (esbuild inlines `tokens.css` + `@font-face` + component CSS). The
  converter scrapes it; tokens land inlined in `_ds_bundle.css` (no separate `tokens/` dir), fonts ship via
  `fonts/fonts.css`. 40 tokens defined / 30 referenced — no `[TOKENS_MISSING]`.
- **Playwright**: the render check uses NODE playwright, installed in `.ds-sync` at **1.58.0** to match the
  cached **chromium-1208** (the Python playwright in user-site populated that cache). A version mismatch
  fails with "Executable doesn't exist". `npm i` warns esbuild's postinstall is blocked by the allow-scripts
  policy — benign here, the esbuild binary is present.
- **`grep` is aliased to `ugrep`** in this shell — it parses `--token:` as a flag. Validate token/class
  presence with Python or `grep -F -- "$tok"`, not bare `grep -F "--tok"`.
- **cardMode overrides**: `ModeBar` + `WorkAreaTabs` are wide (5 modes / 6 tabs) → `cfg.overrides.*.cardMode
  = "column"` so the product grid doesn't crop them. Presentation-only; don't remove.

## Known render warns

- None standing. (ModeBar/WorkAreaTabs `[GRID_OVERFLOW]` resolved via the `column` override above.)

## Re-sync risks (the watch-list)

- **`conventions.md` names real tokens/classes/components.** If `src/tokens.css` renames a token or a
  component is removed, the conventions header goes stale — the conventions step re-validates against the
  fresh build and reports drift; fix the header then.
- **Previews import `@stewie/design-system`** (resolved to `window.StewieDS` at card-compile). If a component
  is renamed, update both its `previews/<Name>.tsx` and any cross-component preview (Panel composes
  MetricTile + Button).
- **Grades are carried forward** by source hash (`.cache/review/*.grade.json`, gitignored). A first re-sync
  on a fresh clone has no local grades but the uploaded `_ds_sync.json` anchors verified-by-upload skips.
- **Toolchain assumed**: node 20, the cached chromium-1208. A newer chromium in the cache needs the matching
  node playwright in `.ds-sync`.
