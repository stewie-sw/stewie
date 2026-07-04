import { expect, test } from "@playwright/test";

// [REQ:RF-03] the first migrated pane (Report) binds REAL backend evidence through the fixture-state
// convention (loading -> ready), at desktop + phone, with zero console errors. Signed in (dev-open director),
// /world + /world/transactions return 200, so the world-state block resolves to `ready` and the timeline to
// ready/empty -- never a blank or stuck-loading pane.
const WIDTHS = [
  { name: "desktop", w: 1280, h: 800 },
  { name: "phone", w: 390, h: 780 },
];

for (const vp of WIDTHS) {
  test(`Report pane binds real world evidence @ ${vp.name}`, async ({ page }) => {
    const errors: string[] = [];
    page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
    page.on("pageerror", (e) => errors.push(e.message));

    await page.setViewportSize({ width: vp.w, height: vp.h });
    await page.goto("/app/report");

    // the world-state block leaves `loading` and resolves to `ready` (director -> /world 200)
    const world = page.locator('[data-testid="report-world"]');
    await expect(world).toHaveAttribute("data-state", "ready", { timeout: 10_000 });
    await expect(world).toContainText("fields");
    await expect(world).toContainText("dem");   // a real layer_id renders (not the "?" placeholder)

    // the execution timeline resolves successfully (ready or empty), never stuck-loading or errored
    await expect(page.locator('[data-testid="report-timeline"]')).toHaveAttribute("data-state", /ready|empty/);

    expect(errors, `console errors @ ${vp.name}: ${errors.join(" | ")}`).toEqual([]);
  });
}
