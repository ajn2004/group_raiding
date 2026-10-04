import { expect, test } from "@playwright/test";

test("home page shows the app and API connection state", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("Group Raiding", { exact: true })).toBeVisible();
  await expect(page.getByRole("status")).toContainText("API connected · v1");
  await expect(page.getByText("Web app running")).toBeVisible();
});
