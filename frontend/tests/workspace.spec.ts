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

  // a reload restores state FROM the URL (the URL is the source of truth)
  await page.reload();
  await expect(page.locator('[data-testid="ws-productMode"]')).toHaveValue("SIM-OPERATE");
  await expect(page.locator('[data-testid="ws-runnableProfile"]')).toHaveValue("ros2_replay");
  await expect(page.locator('[data-testid="ws-physicsBackend"]')).toHaveValue("tier3_chrono");
});

test("Release + Execute defer to the backend eligibility guard (fail-closed with no mission)", async ({ page }) => {
  await page.goto("/app/plan");
  await expect(page.locator('.role-badge[data-role="director"]')).toBeVisible();
  await page.locator('.vtab[data-view="release"]').click(); // client-side nav (director role loaded)

  // no mission selected -> the real /rc/eligibility verdict is NOT eligible -> the pane is refused
  const rel = page.locator('[data-testid="guard-release"]');
  await expect(rel).toBeVisible();
  await expect(rel).not.toContainText("checking eligibility"); // the async verdict resolved
  await expect(rel).toHaveAttribute("data-blocked", "true");
  await expect(rel).toContainText("refused");

  // Execute (metrics) is guarded by the same verdict
  await page.locator('.vtab[data-view="metrics"]').click();
  await expect(page.locator('[data-testid="guard-metrics"]')).toHaveAttribute("data-blocked", "true");
});
