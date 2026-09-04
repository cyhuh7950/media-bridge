import { expect, test } from "@playwright/test";

test("loads and optionally updates the personal npm settings page", async ({ page }) => {
  const expectedPort = process.env.MEDIA_BRIDGE_PERSONAL_E2E_EXPECTED_PORT;
  if (expectedPort === undefined) throw new Error("expected port is required");

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Media Bridge", exact: true })).toBeVisible();
  await expect(page.getByLabel("포트")).toHaveValue(expectedPort);
  await expect(page.getByRole("heading", { name: "Non-Vision LLM" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Vision / OCR 처리 엔진" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "전체 흐름 시험" })).toBeVisible();
  await expect(page.locator("body")).not.toContainText("secret-must-not-appear");

  const savePort = process.env.MEDIA_BRIDGE_PERSONAL_E2E_SAVE_PORT;
  if (savePort !== undefined) {
    await page.getByLabel("포트").fill(savePort);
    await page.getByLabel("에이전트에 설정할 주소").fill(
      `http://127.0.0.1:${savePort}/v1`,
    );
    await page.getByRole("button", { name: "설정 저장" }).click();
    await expect(page.locator("#agent-result")).toContainText("설정을 저장했습니다");
    await expect(page.getByLabel("포트")).toHaveValue(savePort);
  }
});
