import { expect, test } from "@playwright/test";
import { ADMIN, USER, ensureAccount, login, register } from "./helpers";

test.describe.configure({ mode: "serial" });

test("a second user sees none of the first user's documents and cannot run evaluations", async ({ page }) => {
  await ensureAccount(page, ADMIN); // the first account (admin) must exist before this user registers
  await register(page, USER);
  await page.getByRole("link", { name: "Documents", exact: true }).click();
  await expect(page.getByText("No documents found")).toBeVisible();
  await page.getByRole("link", { name: "Evaluation", exact: true }).click();
  await expect(page.getByRole("button", { name: "Run evaluation" })).toHaveCount(0);
  await page.getByRole("link", { name: "AI Assistant", exact: true }).click();
  await page.fill("textarea", "How many days of annual leave do full-time employees accrue?");
  await page.keyboard.press("Enter");
  await expect(page.getByText("couldn't find enough information")).toBeVisible({ timeout: 30_000 });
});

test("administrators can run an evaluation and see the comparison", async ({ page }) => {
  await login(page, ADMIN);
  await page.getByRole("link", { name: "Evaluation", exact: true }).click();
  await page.getByRole("button", { name: "Run evaluation" }).click();
  await expect(page.getByText("Best configuration")).toBeVisible({ timeout: 60_000 });
});

test("production pages send a Content-Security-Policy", async ({ request }) => {
  const res = await request.get("/login");
  const csp = res.headers()["content-security-policy"] ?? "";
  expect(csp).toContain("object-src 'none'");
  expect(csp).toContain("frame-ancestors 'none'");
  expect(csp).toMatch(/connect-src 'self' http:\/\/localhost:8000/);
});

test("theme choice is shared across the app and persists", async ({ page }) => {
  await login(page, ADMIN);
  await page.getByRole("link", { name: "Settings", exact: true }).click();
  await page.getByRole("button", { name: "Dark", exact: true }).click();
  await expect(page.locator("html")).toHaveClass(/dark/);
  await expect(page.locator('[role=radio][aria-checked=true]')).toHaveAttribute("title", "Dark");
  await page.reload();
  await expect(page.locator("html")).toHaveClass(/dark/);
});
