import { expect, test } from "@playwright/test";

// [REQ:RF-02] the workspace state carries the FS-25 route/state model, round-trips through the URL (a link +
// reload restore it), and Release/Execute defer to the REAL backend eligibility verdict (fail-closed).

test("workspace state round-trips through the URL across a reload", async ({ page }) => {
  await page.goto("/app/plan");
  await expect(page.locator('.role-badge[data-role="director"]')).toBeVisible();

  await page.locator('[data-testid="ws-productMode"]').selectOption("SIM-OPERATE");
  await page.locator('[data-testid="ws-runnableProfile"]').selectOption("ros2_replay");
  await page.locator('[data-testid="ws-physicsBackend"]').selectOption("tier3_chrono");

  // the routeable state is written to the URL query params
  await expect
    .poll(() => new URL(page.url()).searchParams.get("productMode"))
    .toBe("SIM-OPERATE");
  const sp = new URL(page.url()).searchParams;
  expect(sp.get("runnableProfile")).toBe("ros2_replay");
  expect(sp.get("physicsBackend")).toBe("tier3_chrono");

  // navigating BETWEEN panes preserves the workspace state (the nav links carry the query params)
  await page.locator('.vtab[data-view="report"]').click();
  expect(new URL(page.url()).searchParams.get("productMode")).toBe("SIM-OPERATE");
  await expect(page.locator('[data-testid="ws-productMode"]')).toHaveValue("SIM-OPERATE");

  // a reload restores state FROM the URL (the URL is the source of truth)
  await page.reload();
  await expect(page.locator('[data-testid="ws-productMode"]')).toHaveValue("SIM-OPERATE");
  await expect(page.locator('[data-testid="ws-runnableProfile"]')).toHaveValue("ros2_replay");
  await expect(page.locator('[data-testid="ws-physicsBackend"]')).toHaveValue("tier3_chrono");
});

// [REQ:GW-02] the FULL PRD2 unified context (branch/release/run/selection/layers) round-trips through the URL,
// even though these fields have no rail selector — the URL is the source of truth. Injecting them via the URL
// then changing a rail field re-serializes the WHOLE state, so the injected context must persist (proving
// fromSearchParams parsed it into state and toSearchParams wrote it back).
test("[GW-02] URL-injected mission-lifecycle context survives a rail change", async ({ page }) => {
  await page.goto("/app/plan?branch=sim-1&release=rel-2&run=run-3&selectedEntity=wp-1&layers=base.dem,hazard.rocks");
  await expect(page.locator('.role-badge[data-role="director"]')).toBeVisible();

  await page.locator('[data-testid="ws-productMode"]').selectOption("SIM-OPERATE");
  await expect.poll(() => new URL(page.url()).searchParams.get("productMode")).toBe("SIM-OPERATE");

  const sp = new URL(page.url()).searchParams;
  expect(sp.get("branch")).toBe("sim-1");
  expect(sp.get("release")).toBe("rel-2");
  expect(sp.get("run")).toBe("run-3");
  expect(sp.get("selectedEntity")).toBe("wp-1");
  expect(sp.get("layers")).toBe("base.dem,hazard.rocks");
});

test("Release + Execute defer to the backend eligibility guard (fail-closed with no mission)", async ({ page }) => {
  await page.goto("/app/plan");
  await expect(page.locator('.role-badge[data-role="director"]')).toBeVisible();
  await page.locator('.vtab[data-view="release"]').click(); // client-side nav (director role loaded)

  // no mission selected -> the real /rc/eligibility verdict is NOT eligible -> the pane is refused (FR-03)
  const rel = page.locator('[data-testid="verdict-release"]');
  await expect(rel).toBeVisible(); // the async verdict resolved (only rendered when ready)
  await expect(rel).toHaveAttribute("data-blocked", "true");
  await expect(rel).toContainText("REFUSED");

  // Execute (metrics) is guarded by the same verdict
  await page.locator('.vtab[data-view="metrics"]').click();
  await expect(page.locator('[data-testid="verdict-metrics"]')).toHaveAttribute("data-blocked", "true");
});
