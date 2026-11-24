import { devices, expect, test } from "@playwright/test";
import { ADMIN, login } from "./helpers";

// iPhone 13 viewport, touch and user agent, rendered with Chromium (WebKit is not required in CI).
const { viewport, userAgent, deviceScaleFactor, isMobile, hasTouch } = devices["iPhone 13"];
test.use({ viewport, userAgent, deviceScaleFactor, isMobile, hasTouch });

for (const route of ["/", "/chat", "/documents", "/collections", "/settings"]) {
  test(`no horizontal overflow on ${route} at phone width`, async ({ page }) => {
    await login(page, ADMIN);
    await page.goto(route);
    await page.waitForLoadState("networkidle");
    const { scroll, width } = await page.evaluate(() => ({
      scroll: document.documentElement.scrollWidth, width: document.documentElement.clientWidth }));
    expect(scroll).toBeLessThanOrEqual(width);
  });
}

test("form fields use at least 16px text on phones (iOS Safari zooms in otherwise)", async ({ page }) => {
  // Regression: 14px fields made iOS auto-zoom on focus and the page looked cut off.
  await login(page, ADMIN);
  await page.goto("/chat");
  const size = await page.locator("textarea").evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
  expect(size).toBeGreaterThanOrEqual(16);
  await page.goto("/documents");
  const sizes = await page.locator("input.input, select.input").evaluateAll((els) =>
    els.map((el) => parseFloat(getComputedStyle(el).fontSize)));
  expect(Math.min(...sizes)).toBeGreaterThanOrEqual(16);
});
