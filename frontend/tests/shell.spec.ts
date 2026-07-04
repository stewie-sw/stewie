import { expect, test } from "@playwright/test";

import { PANES } from "../src/panes";

// [REQ:RF-01] signed-in (dev-open director on loopback) the React shell shows the SAME 13 pane identities as
// the vanilla cockpit and every pane opens, at desktop AND phone widths, with zero console errors.
const WIDTHS = [
  { name: "desktop", w: 1280, h: 800 },
  { name: "phone", w: 390, h: 780 },
];

for (const vp of WIDTHS) {
  test(`shell shows + opens all 13 panes as director @ ${vp.name}`, async ({ page }) => {
    const errors: string[] = [];
    page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
    page.on("pageerror", (e) => errors.push(e.message));

    await page.setViewportSize({ width: vp.w, height: vp.h });
    await page.goto("/app/plan");

    // wait for the async /auth/me role fetch to resolve to director (loopback dev-open) before asserting
    // visibility -- otherwise the first paint is guest and the director-gated tabs are legitimately hidden.
    await expect(page.locator('.role-badge[data-role="director"]')).toBeVisible();

    // director sees all 13 tabs in the nav
    expect(PANES.length).toBe(13);
    for (const p of PANES) {
      await expect(page.locator(`.vtab[data-view="${p.id}"]`)).toBeVisible();
    }
    // open every pane via client-side nav (preserves the loaded director role) + assert its identity renders
    for (const p of PANES) {
      await page.locator(`.vtab[data-view="${p.id}"]`).click();
      await expect(page.locator(`section[data-pane="${p.id}"]`)).toBeVisible();
    }
    expect(errors, `console errors @ ${vp.name}: ${errors.join(" | ")}`).toEqual([]);
  });
}
