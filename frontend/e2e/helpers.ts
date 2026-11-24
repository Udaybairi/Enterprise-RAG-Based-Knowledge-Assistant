import { expect, type Page } from "@playwright/test";
import path from "node:path";

export const ADMIN = { name: "Dana Admin", email: "dana@acme.example", password: "Passw0rd!123" };
export const USER = { name: "Uma User", email: "uma@acme.example", password: "Passw0rd!456" };
export const fixture = (name: string) => path.join(__dirname, "fixtures", name);

export async function register(page: Page, u: typeof ADMIN) {
  await page.goto("/register");
  await page.fill("#name", u.name);
  await page.fill("#email", u.email);
  await page.fill("#password", u.password);
  await page.click('button:has-text("Create account")');
  await expect(page.getByRole("heading", { name: /Welcome back/ })).toBeVisible();
}

export const API = "http://localhost:8000";

/** Create the account if it does not exist yet, so every spec can run on its own. */
export async function ensureAccount(page: Page, u: typeof ADMIN) {
  const r = await page.request.post(`${API}/api/auth/register`, {
    data: { email: u.email, password: u.password, full_name: u.name },
  });
  expect([201, 409]).toContain(r.status());
}

export async function login(page: Page, u: typeof ADMIN) {
  await ensureAccount(page, u);
  await page.goto("/login");
  await page.fill("#email", u.email);
  await page.fill("#password", u.password);
  await page.click('button:has-text("Sign in")');
  await expect(page.getByRole("heading", { name: /Welcome back/ })).toBeVisible();
}

/** Fail the test on uncaught page errors or Content-Security-Policy violations. */
export function watchErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  page.on("console", (m) => {
    if (m.type() === "error" && /Content Security Policy|Refused to/i.test(m.text())) errors.push(`csp: ${m.text()}`);
  });
  return errors;
}

/** Resolves once an answer has finished streaming (grounded badge or refusal is rendered). */
export async function waitForAnswer(page: Page, count: number) {
  await expect(page.locator(".prose-chat")).toHaveCount(count, { timeout: 30_000 });
  await expect(page.locator('button[aria-label="Send"]')).toBeAttached({ timeout: 30_000 });
}
