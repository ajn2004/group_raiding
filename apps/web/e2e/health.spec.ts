import { expect, test } from "@playwright/test";

test("home page shows the app and API connection state", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "The web app is running" })).toBeVisible();
  await expect(page.getByRole("status")).toContainText("Python API connected (version v1)");
});
