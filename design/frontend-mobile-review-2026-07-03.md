# STEWIE Frontend Mobile Review - 2026-07-03

## Verdict

STEWIE's mobile frontend is partially coherent but not production-grade on phones. The main cockpit has a responsive shell, passes the existing static/mobile overflow guards, and avoids page-level horizontal scrolling at tested phone and tablet widths. However, critical operational chrome is still embedded inside a horizontally scrolling tab strip, so health, alerts, workspace/account controls, More work areas, Settings, System, and Admin are not reliably visible or usable on mobile. The `/program` board now fits the viewport horizontally, but its filter buttons, search input, and row chips are far below mobile touch-target size. The current regression suite proves several useful layout invariants, but it does not yet test the full mobile command surface.

## Review Scope

- Skill applied: `frontend-review-design`.
- Runtime: local server at `http://127.0.0.1:8773` with dev-open/operator-login disabled for audit access.
- Browser: Playwright using system Chrome.
- Viewports tested: `320x568`, `360x640`, `390x844`, `430x932`, `768x1024`.
- Screens captured: `design/mobile-review-2026-07-03-screenshots/mobile-review-*-initial.png`, `design/mobile-review-2026-07-03-screenshots/mobile-review-*-drawer.png`, `design/mobile-review-2026-07-03-screenshots/mobile-review-*-program.png`, `design/mobile-review-2026-07-03-screenshots/mobile-review-*-toolbox.png`.
- Existing tests run: `stewie/server/test_ia_provenance_labels.py`, `stewie/server/test_program_mobile.py`, `stewie/server/test_a11y.py`, `stewie/server/test_ux_clusterb.py`.

## Evidence Summary

- Existing pytest mobile/static guards pass: `16 passed, 1 warning`.
- No page-level horizontal overflow was observed on the cockpit or `/program` at any tested viewport.
- The cockpit emitted no browser console errors or page errors in the custom mobile pass.
- Drawer button touch target is correct at all tested sizes: `44x44`.
- Cockpit visible button targets checked in the active view meet the `44px` floor.
- `/program` rendered 255 row chips and fit the viewport, but 263 interactive controls measured below the `44px` mobile target floor.
- More/profile menus overflowed the visible viewport on every tested phone size and still overflowed on the tablet viewport when opened from their current tab-strip coordinates.
- The Plan ToolBox is reachable and its main buttons mostly hit `44px`, but the expanded tray clips at `320px` and the keep-out radius input is only about `29px` high.

## Findings

### P1 - Critical Mobile Chrome Is Offscreen

The primary work tabs, overflow menu, health chip, alert button, workspace badge, and account menu all live inside `#viewtabs` in `stewie/server/index.html:787`. On mobile, `#viewtabs` is intentionally made horizontally scrollable in `stewie/server/index.html:222`, but that also pushes critical status and account controls out of the first viewport.

Measured at phone widths:

- `#morewrap` starts around `x=570`.
- `#healthchip` starts around `x=626`.
- `#alertbtn` starts around `x=680`.
- `#whoami` starts around `x=734`.

Impact: a phone operator can see Plan/Rehearse/Validate/Execute/Report, but health, alerts, account, Settings, System, Admin, and some role-gated work areas are effectively hidden behind horizontal tab scrolling. For mission-style software, health and alert state cannot be optional overflow content.

Recommendation:

- Split the mobile shell into two zones:
  - A fixed, non-scrolling mobile top bar for drawer, health, alerts, workspace state, and account.
  - A horizontally scrollable work-area tab rail for Plan/Rehearse/Validate/Release/Execute/Report only.
- Move System/Settings/Admin entry points into a viewport-safe account sheet, not a tab-strip-positioned popover.
- Keep the desktop layout visually similar, but do not let the mobile status plane depend on horizontal tab scroll position.

### P1 - More/Profile Menus Render Outside The Viewport

`#moremenu` and `#profmenu` are absolutely positioned inside tab-strip children in `stewie/server/index.html:819` and `stewie/server/index.html:862`. Because their parents are located far to the right of the scrollable strip, the menus open outside the visible viewport on phones.

Measured menu boxes:

- More menu right edge: about `624px`.
- Profile menu right edge: about `881px`.
- This overflows `320`, `360`, `390`, `430`, and even the visible `768px` tablet viewport in the tested initial scroll state.

Impact: role-gated and administrative functions can exist in DOM but be unusable on mobile. This is a serious control-panel issue because it breaks recovery, account, admin, and system-diagnostic workflows.

Recommendation:

- On mobile, render More/profile menus as `position: fixed` viewport overlays or bottom sheets.
- Clamp popover geometry to the viewport:
  - `left >= 8px`
  - `right <= window.innerWidth - 8px`
  - `max-height <= visualViewport.height - safe-area-insets - chrome`
- Add an automated Playwright assertion that opens each menu at `320`, `390`, `430`, and `768` widths and fails if any menu rect leaves the viewport.

### P1 - `/program` Fits Width But Fails Touch Ergonomics

The `/program` page has good horizontal overflow guards in `stewie/server/web/program.html:30`: grid columns collapse, min-width is zeroed, long content wraps, and the ConOps spine self-scrolls. The smoke check also verifies no horizontal overflow at `390px` in `scripts/ui_smoke.mjs:159`.

The problem is touch size. Current CSS sets compact desktop-like controls:

- `.fbtn` at `stewie/server/web/program.html:56` measured about `24px` high.
- `#program-search` at `stewie/server/web/program.html:62` measured about `26px` high.
- `.rowchip` at `stewie/server/web/program.html:83` measured about `22px` high.

The browser pass found 263 interactive controls below `44px` height.

Impact: `/program` is readable on mobile but not comfortably operable. This is especially risky because `/program` is a requirement/traceability board with dense filtering, search, and row selection.

Recommendation:

- Add a mobile media block for `/program`:
  - `.fbtn`, `.rowchip`, and `#program-search` should have `min-height: 44px`.
  - Search should become full-width or flex-basis `100%` under phone widths.
  - Filter controls should wrap in grouped rows with visible active state.
  - Row chips should become tappable rows or larger chips with enough inline spacing.
- Add a runtime mobile test for `/program` touch target size, not just body overflow.

### P1 - Plan ToolBox Clips And Has An Undersized Numeric Control

The Plan edit ToolBox is defined in `stewie/server/index.html:937` and controlled by mobile positioning rules around `stewie/server/index.html:204` and `stewie/server/index.html:242`. The ToolBox trigger itself is reachable on mobile and measures about `69x44`, but the expanded tray is still a dense desktop-style absolute toolbar.

Measured behavior:

- At `320x568`, the expanded `#edittools` rect was about `x=50`, `w=272`, `right=322`, so the tray clips past the visible viewport by about `2px`.
- At `320x568`, the `note` and `poly` controls also measured `right=322`, outside the viewport.
- At `390px`, `430px`, and `768px`, the expanded tray stayed within the viewport.
- `#koradius`, the keep-out radius input in `stewie/server/index.html:952`, measured about `52x29` at all tested mobile sizes, below the `44px` touch target floor.
- The expanded tray covers a large chunk of the map: about `229x205` at `320px`, `275x205` at `390px`, and `525x123` at tablet width.

Impact: the ToolBox works better than the top chrome menus, but it is not yet a reliable phone-first editing surface. At the smallest supported phone width it clips horizontally, and the key barrier-radius control is too small for touch. Because ToolBox controls place waypoints, lander, rover, keep-outs, polygons, notes, landmarks, and measurements, this is a mission-planning input risk rather than a cosmetic issue.

Recommendation:

- Convert the expanded mobile ToolBox into a viewport-contained sheet or drawer section instead of a free-floating absolute toolbar.
- Make `#koradius` and its enclosing radius control a full mobile row with `min-height: 44px`, an explicit label, and stepper-friendly input sizing.
- On phones, group edit tools into clear sections: Place, Barriers, Measure/Edit, Done.
- Add a mobile assertion that opens `#editmode` at `320`, `390`, `430`, and `768` and verifies every visible `#edittoolbar` button/input remains inside the viewport and meets the `44px` target.
- Keep the current compact floating ToolBox for desktop/tablet only if the viewport has enough width.

### P2 - Mobile Regression Coverage Is Too Narrow

The existing tests cover important pieces, but not the complete mobile control surface:

- `stewie/server/test_ia_provenance_labels.py:167` checks the mobile breakpoint, `44px` touch-target CSS existence, and provenance chip visibility.
- `scripts/ux_a11y_smoke.py:198` checks only `.vtab` and `#drawerbtn` dimensions at `390px`.
- `stewie/server/test_program_mobile.py:1` explicitly says the cockpit half of the mobile overflow guarantee is still open.
- `scripts/ui_smoke.mjs:159` checks `/program` horizontal overflow, not touch targets or menu geometry.

Impact: the codebase can pass current mobile tests while still shipping offscreen command chrome and undersized touch controls.

Recommendation:

- Add a dedicated `scripts/mobile_review_smoke.mjs` or expand `scripts/ux_a11y_smoke.py`.
- Required assertions:
  - No body horizontal overflow at `320`, `360`, `390`, `430`, and `768`.
  - Health, alerts, workspace/account controls are visible in the first viewport on phones.
  - More and profile menus remain within the viewport when opened.
  - The Plan ToolBox remains viewport-contained when opened.
  - All visible interactive controls in cockpit and `/program` are at least `44x44`, or are explicitly marked non-touch/non-primary with a justified exemption.
  - Plan, Validate, Execute, Report, Settings, System, and Admin panes can be activated without body overflow.
  - Drawer open/close preserves focus and does not trap content behind the drawer button.

### P2 - Mobile Information Architecture Needs A Control-Plane Split

The mobile cockpit currently treats work-area navigation and system command/status controls as one strip. That is the root cause behind the offscreen health/account/menu problems.

Recommendation:

- Use this mobile hierarchy:
  - Top status bar: drawer, health, alerts, workspace/live-training, account.
  - Primary workflow rail: Plan, Rehearse, Validate, Release, Execute, Report.
  - Contextual subnav: Validate sub-tabs, pane-specific toolbars, or mission-stepper state.
  - Drawer: mission inputs, site/structure/vehicle selection, longer form controls.
  - Account/system sheet: Settings, System, Admin, Program board, sign out.

This structure keeps operational safety/status controls stable while allowing the workflow rail to scroll.

## File-Level Recommendations

### `stewie/server/index.html`

- Move `#healthchip`, `#alertbtn`, `#wsbadge`, and `#whoami` out of `#viewtabs` for mobile, or duplicate them into a mobile-only top bar fed by the same state renderers.
- Keep `#viewtabs` focused on work-area tabs only at phone widths.
- Replace mobile `#moremenu` and `#profmenu` absolute positioning with a viewport-clamped overlay/bottom sheet.
- Refactor the expanded `#edittoolbar`/`#edittools` mobile presentation into a viewport-contained sheet or drawer group.
- Raise `#koradius` and its surrounding radius control to the same `44px` mobile touch target standard as other ToolBox controls.
- Add CSS using `env(safe-area-inset-top)` and `env(safe-area-inset-bottom)` so top/bottom controls behave correctly on notched devices.
- Preserve the current drawer behavior; the `#drawerbtn` target size and drawer body scroll behavior are acceptable.

### `stewie/server/web/program.html`

- Add mobile touch-target sizing for `.fbtn`, `.rowchip`, and `#program-search`.
- Convert the mobile filter deck into a stacked control area where search is full-width and filter buttons wrap into `44px` rows.
- Consider representing PRD matrix rows as a compact list on phones instead of hundreds of tiny chips.
- Keep the existing no-horizontal-overflow guards; they are working.

### `scripts/ux_a11y_smoke.py`

- Expand the mobile target check beyond `.vtab` and `#drawerbtn`.
- Add menu-open geometry assertions.
- Add ToolBox-open geometry and touch-target assertions.
- Add first-viewport visibility assertions for health, alerts, account, and workspace controls.

### `scripts/ui_smoke.mjs`

- Keep the `/program` no-overflow assertion.
- Add `/program` mobile touch-target assertions.
- If CI cannot rely on bundled Chromium, support a system Chrome channel or document the required browser install path.

### `stewie/server/test_program_mobile.py`

- Update the documented guarantee after adding the runtime touch-target check.
- Add a static guard that `/program` carries a mobile media block with `min-height: 44px` for the filter/search/chip controls.

## Mobile Acceptance Criteria

- At `320x568`, `360x640`, `390x844`, `430x932`, and `768x1024`, `document.scrollingElement.scrollWidth <= window.innerWidth + 1` on cockpit and `/program`.
- At phone widths, health, alerts, workspace/account controls are visible without horizontal tab scrolling.
- Opening More/profile menus never creates an offscreen menu rect.
- Opening the Plan ToolBox keeps every visible edit control within the viewport at `320`, `390`, `430`, and `768` widths.
- Every visible ToolBox button/input, including keep-out radius, is at least `44px` high on mobile.
- All visible interactive controls are at least `44x44` on mobile unless explicitly exempted.
- `/program` search, filters, and row selectors remain operable by touch.
- Drawer, top bar, tab rail, stepper, and pane scroll areas do not overlap in a way that hides content.
- Plan, Validate, Execute, Report, Settings, System, and Admin can be activated and scrolled on mobile.

## Minimum Fix Plan

1. Refactor the cockpit mobile chrome into a non-scrolling status/action bar plus scrollable workflow tabs.
2. Convert More/profile menus to viewport-fixed mobile sheets.
3. Convert the expanded Plan ToolBox into a viewport-contained mobile sheet and fix the keep-out radius input target size.
4. Add `/program` mobile touch-target CSS and adjust filter/search/chip layout.
5. Add a mobile smoke test that runs the five viewport sizes used in this review.
6. Gate CI on no horizontal overflow, no offscreen menus, visible critical chrome, ToolBox containment, and touch-target compliance.

## What Already Works

- Cockpit body-level horizontal overflow is controlled in the tested viewports.
- `/program` body-level horizontal overflow is controlled.
- The drawer trigger meets mobile target sizing.
- The ToolBox trigger is reachable and meets the `44px` height floor.
- Main cockpit panes use internal scrolling instead of forcing page overflow.
- Existing tests already protect several important mobile CSS invariants.

## Residual Risk

This review used desktop Chrome emulation, not physical iOS Safari or Android Chrome. After the structural fixes, test on at least one real iOS device and one Android device, specifically for visual viewport behavior, safe-area insets, soft keyboard interaction in `/program` search, and fixed-position menu sheets.
