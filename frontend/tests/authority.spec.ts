import { expect, test } from "@playwright/test";

// [REQ:FR-03] the Release + Execute authority panel. Release: the complete /rc/eligibility gate evidence +
// a director sign-off of a REAL prepared mission that renders the 7-field command-authority card (clause 1).
// Execute: the refusal reason surfaced when ineligible (clause 2). Role-gated panes -> nav after director.
async function toPane(page: import("@playwright/test").Page, view: string) {
  await page.goto("/app/plan");
  await expect(page.locator('.role-badge[data-role="director"]')).toBeVisible();
  await page.locator(`.vtab[data-view="${view}"]`).click();
}

test("Release: gate evidence + a released revision shows every authority field", async ({ page }) => {
  await toPane(page, "release");
  await expect(page.locator('[data-testid="authority-release"]')).toHaveAttribute("data-state", "ready", { timeout: 10_000 });
  await expect(page.locator('[data-testid="gates-release"]')).toBeVisible();

  // sign off a prepared mission -> the frozen 7-field command-authority card (clause 1)
  await page.selectOption('[data-testid="release-mission"]', "01_flatten_pad");
  await page.locator('[data-testid="release-btn"]').click();
  const card = page.locator('[data-testid="command-authority"]');
  await expect(card).toBeVisible({ timeout: 10_000 });
  for (const f of ["plan hash", "signed by", "runtime profile", "sensor profile", "namespace", "authorized", "watchdog"]) {
    await expect(card).toContainText(f);
  }
});

test("[dispatch-audit R7a] the release POST echoes the double-submit CSRF token", async ({ page, context }) => {
  // SEC-01: a cookie-authenticated state-changing POST must echo the readable stewie_csrf cookie in the
  // X-CSRF-Token header (the backend guard 403s otherwise). dev-open loopback bypasses the guard, so this
  // asserts the FRONTEND sends the header by intercepting the outgoing /executive/release-plan request.
  await context.addCookies([{ name: "stewie_csrf", value: "csrf-r7a-token", url: "http://127.0.0.1:8391" }]);
  await toPane(page, "release");
  await expect(page.locator('[data-testid="authority-release"]')).toHaveAttribute("data-state", "ready", { timeout: 10_000 });
  const reqP = page.waitForRequest((r) => r.url().includes("/executive/release-plan") && r.method() === "POST");
  await page.selectOption('[data-testid="release-mission"]', "01_flatten_pad");
  await page.locator('[data-testid="release-btn"]').click();
  const req = await reqP;
  expect(req.headers()["x-csrf-token"]).toBe("csrf-r7a-token");
});

test("Execute surfaces the refusal reason when ineligible (clause 2)", async ({ page }) => {
  await toPane(page, "metrics");
  const verdict = page.locator('[data-testid="verdict-metrics"]');
  await expect(verdict).toBeVisible({ timeout: 10_000 });
  await expect(verdict).toHaveAttribute("data-eligible", "false");
  await expect(verdict).toContainText("REFUSED");
  await expect(page.locator('[data-testid="gates-metrics"]')).toBeVisible();
});

test("[FR-02] depth-source selector + health; an absent source degrades Release", async ({ page }) => {
  await page.goto("/app/plan");
  await expect(page.locator('.role-badge[data-role="director"]')).toBeVisible();
  // the Validate pane shows the depth-source table with real health + the selector
  await page.locator('.vtab[data-view="validate"]').click();
  await expect(page.locator('[data-testid="depth-sources"]')).toHaveAttribute("data-state", "ready", { timeout: 10_000 });
  const table = page.locator('[data-testid="depth-table"]');
  await expect(table).toContainText("stereo_front");
  await expect(table).toContainText("absent"); // lidar_front health
  // pick an absent source -> Release is degraded/blocked with a legible reason
  await page.selectOption('[data-testid="ws-depthSource"]', "lidar_front");
  await page.locator('.vtab[data-view="release"]').click();
  const degraded = page.locator('[data-testid="depth-degraded-release"]');
  await expect(degraded).toBeVisible({ timeout: 10_000 });
  await expect(degraded).toContainText("absent");
});

test("[FR-01] a runnable-profile mismatch degrades Release; the shell shows mode + profile", async ({ page }) => {
  // the rail always shows the active product mode + runnable profile (state contract, visible in the shell)
  await page.goto("/app/plan");
  await expect(page.locator('.role-badge[data-role="director"]')).toBeVisible();
  await expect(page.locator('[data-testid="ws-productMode"]')).toBeVisible();
  await expect(page.locator('[data-testid="ws-runnableProfile"]')).toBeVisible();
  // default runnable profile (desktop_sil) != the system's active command-authority profile -> degraded
  await page.locator('.vtab[data-view="release"]').click();
  const mismatch = page.locator('[data-testid="profile-mismatch-release"]');
  await expect(mismatch).toBeVisible({ timeout: 10_000 });
  await expect(mismatch).toContainText("degraded");
});
