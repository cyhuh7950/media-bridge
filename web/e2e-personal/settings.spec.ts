import { expect, test } from "@playwright/test";

test("loads and optionally updates the personal npm settings page", async ({ page }) => {
  const expectedPort = process.env.MEDIA_BRIDGE_PERSONAL_E2E_EXPECTED_PORT;
  if (expectedPort === undefined) throw new Error("expected port is required");

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Media Bridge 설정" })).toBeVisible();
  await expect(page.getByLabel("Media Bridge 포트")).toHaveValue(expectedPort);
  await expect(page.locator("body")).not.toContainText("secret-must-not-appear");

  const savePort = process.env.MEDIA_BRIDGE_PERSONAL_E2E_SAVE_PORT;
  if (savePort !== undefined) {
    await page.getByLabel("Media Bridge 포트").fill(savePort);
    await page.getByLabel("OpenCodex에 설정할 Media Bridge 주소").fill(
      `http://127.0.0.1:${savePort}/v1`,
    );
    await page.getByRole("button", { name: "설정 저장" }).click();
    await expect(page.getByRole("status")).toContainText("mb service restart");
    await expect(page.getByLabel("Media Bridge 포트")).toHaveValue(savePort);
  }
});
