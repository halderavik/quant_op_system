import { expect, test } from "@playwright/test";

test("home shell renders the project composer", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "SRAS", exact: true })).toBeVisible();
  await expect(page.getByLabel("New project")).toBeVisible();
  await expect(page.getByLabel("Message")).toBeVisible();
});
