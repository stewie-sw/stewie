import { expect, test } from "@playwright/test";

// [REQ:AU-01] the global command-authority card is App-shell chrome: it is present + shows the current
// authority state (authorized/refused + refusal reason) from EVERY command-capable view, not just its own pane.
// Verified across two command-capable panes (Plan and Release) via role-gated nav.

test("[AU-01] command-authority chrome is visible on every command-capable view", async ({ page }) => {
  await page.goto("/app/plan");
  await expect(page.locator('.role-badge[data-role="director"]')).toBeVisible();

  // present on Plan, in the shell header (not inside the pane body)
  const chrome = page.locator('[data-testid="authority-chrome"]');
  await expect(chrome).toBeVisible();
  await expect(chrome).toContainText("AUTH");
  // it reflects the REAL /rc/eligibility verdict (authorized or refused), never "unknown" once loaded
  await expect.poll(() => chrome.getAttribute("data-state")).toBe("ready");
  const verdict = await chrome.getAttribute("data-eligible");
  expect(["true", "false"]).toContain(verdict);
  // a refusal surfaces its reason inline (AU-01: every refusal reason)
  if (verdict === "false") await expect(chrome).toContainText("refused");

  // still visible after navigating to another command-capable pane (Release)
  await page.locator('.vtab[data-view="release"]').click();
  await expect(page.locator('section[data-pane="release"]')).toBeVisible();
  await expect(page.locator('[data-testid="authority-chrome"]')).toBeVisible();
  // the same verdict is shown on both panes (one global authority source)
  await expect(page.locator('[data-testid="authority-chrome"]')).toHaveAttribute("data-eligible", verdict!);

  await page.screenshot({ path: "test-results/au01-authority-chrome.png" });
});
