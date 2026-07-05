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

test("Execute surfaces the refusal reason when ineligible (clause 2)", async ({ page }) => {
  await toPane(page, "metrics");
  const verdict = page.locator('[data-testid="verdict-metrics"]');
  await expect(verdict).toBeVisible({ timeout: 10_000 });
  await expect(verdict).toHaveAttribute("data-eligible", "false");
  await expect(verdict).toContainText("REFUSED");
  await expect(page.locator('[data-testid="gates-metrics"]')).toBeVisible();
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
