import { expect, test } from "@playwright/test";
import { ADMIN, fixture, login, waitForAnswer, watchErrors } from "./helpers";

test.describe.configure({ mode: "serial" });

test("unauthenticated visitors are sent to the login page", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/login/);
});

test("full workflow: upload, process, ask with citations, open evidence, follow up, refuse", async ({ page }) => {
  const errors = watchErrors(page);
  await login(page, ADMIN);

  // upload three formats; each is processed and reaches Ready
  await page.getByRole("link", { name: "Documents", exact: true }).click();
  await page.setInputFiles("input[type=file]", [
    fixture("Employee_Handbook.pdf"), fixture("Security_Guidelines.md"), fixture("Benefits.docx"),
  ]);
  await expect(page.getByText("3 document(s) uploaded for processing")).toBeVisible({ timeout: 30_000 });
  await expect(page.locator("tbody tr")).toHaveCount(3);
  await expect(page.locator("tbody tr", { hasText: "Ready" })).toHaveCount(3, { timeout: 30_000 });

  // processing log is visible to the user
  await page.getByRole("button", { name: "Details for Employee_Handbook.pdf" }).click();
  await expect(page.getByText("Processing log")).toBeVisible();
  await expect(page.locator("ol")).toContainText("header/footer");
  await page.keyboard.press("Escape");

  // grounded, cited, streamed answer
  await page.getByRole("link", { name: "AI Assistant", exact: true }).click();
  await page.fill("textarea", "How many days of annual leave do full-time employees accrue?");
  await page.keyboard.press("Enter");
  await waitForAnswer(page, 1);
  await expect(page.locator(".prose-chat").first()).toContainText("25 days");
  await expect(page.getByText(/Grounded in \d+ source/)).toBeVisible();
  await expect(page.getByText("Employee_Handbook.pdf").first()).toBeVisible();

  // a citation opens the document at the cited page with the passage highlighted
  await page.locator(".prose-chat button").first().click();
  await expect(page.getByText("cited passage highlighted")).toBeVisible();
  await expect(page.locator("#viewer-text mark").first()).toBeVisible();
  await page.keyboard.press("Escape");

  // follow-up question is resolved against the conversation
  await page.fill("textarea", "How far in advance must it be requested?");
  await page.keyboard.press("Enter");
  await waitForAnswer(page, 2);
  await expect(page.getByText(/searched: /)).toBeVisible();

  // a question the documents cannot answer is refused, not invented
  await page.fill("textarea", "What is the dress code for the Antarctica office?");
  await page.keyboard.press("Enter");
  await waitForAnswer(page, 3);
  await expect(page.getByText("couldn't find enough information")).toBeVisible();
  await expect(page.getByText("No supporting sources")).toBeVisible();

  // feedback is recorded on the answer
  const helpful = page.getByRole("button", { name: "Helpful" }).last();
  await helpful.click();
  await expect(helpful).toHaveAttribute("aria-pressed", "true");

  expect(errors).toEqual([]);
});

test("dashboard reflects processed documents", async ({ page }) => {
  await login(page, ADMIN);
  await expect(page.getByRole("heading", { name: "Processing activity" })).toBeVisible();
  await expect(page.getByText("100% success")).toBeVisible();
});
