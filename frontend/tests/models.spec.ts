import { expect, test } from "@playwright/test";

// [REQ:BD-03] the Models pane binds the REAL /physics/compatibility matrix: the default body (moon) reads
// SUPPORTED, the matrix renders, and switching the body selector to a MICROGRAVITY body (Bennu) flips the
// verdict to REFUSED with the regime reason -- the fail-closed rule surfaced in the UI.
test("Models pane shows compatibility verdict + regime refusal on body switch @ desktop", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push(e.message));

  // Models is operator-gated: land on a guest-visible pane, wait for the async role fetch to resolve to
  // director, THEN client-side-nav to Models (a direct deep-link would redirect while role is still guest).
  await page.goto("/app/plan");
  await expect(page.locator('.role-badge[data-role="director"]')).toBeVisible();
  await page.locator('.vtab[data-view="models"]').click();

  const verdict = page.locator('[data-testid="models-verdict"]');
  await expect(verdict).toHaveAttribute("data-state", "ready", { timeout: 10_000 });
  await expect(verdict).toContainText("SUPPORTED"); // default body=moon, backend=tier2_numpy
  await expect(page.locator('[data-testid="models-matrix"] table.compat')).toBeVisible();

  // switch to a microgravity body -> the verdict flips to REFUSED (fail-closed regime rule)
  await page.selectOption('[data-testid="ws-body"]', "bennu");
  await expect(verdict).toContainText("REFUSED");
  await expect(verdict).toContainText("microgravity");

  // the SOIL OVERRIDE (allow_analog) flips Bennu to SUPPORTED-via-analog (caveated)
  await page.locator('[data-testid="models-allow-analog"]').check();
  await expect(verdict).toContainText("SUPPORTED");
  await expect(verdict).toContainText("analog");

  expect(errors, `console errors: ${errors.join(" | ")}`).toEqual([]);
});

test("Models pane renders the matrix @ phone", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 780 });
  await page.goto("/app/plan");
  await expect(page.locator('.role-badge[data-role="director"]')).toBeVisible();
  await page.locator('.vtab[data-view="models"]').click();
  await expect(page.locator('[data-testid="models-matrix"]')).toHaveAttribute("data-state", "ready", {
    timeout: 10_000,
  });
});
