import fs from "node:fs/promises";

import AxeBuilder from "@axe-core/playwright";
import { expect, test, type BrowserContext, type Page } from "@playwright/test";

const baseURL = "https://127.0.0.1:18443";
const stateFile = "/tmp/media_bridge_p2a_tools_01a02e88/e2e-state.json";
const adminPassword = "P2a-local-browser-password-2026!";
const operatorPassword = "P2a-local-operator-password-2026!";
const viewerPassword = "P2a-local-viewer-password-2026!";

interface E2eState {
  bootstrap_token: string;
}

async function readState(): Promise<E2eState> {
  const parsed: unknown = JSON.parse(await fs.readFile(stateFile, "utf-8"));
  if (
    typeof parsed !== "object"
    || parsed === null
    || !("bootstrap_token" in parsed)
    || typeof parsed.bootstrap_token !== "string"
  ) {
    throw new Error("invalid e2e state");
  }
  return { bootstrap_token: parsed.bootstrap_token };
}

async function loginApi(context: BrowserContext, username: string, password: string) {
  const response = await context.request.post(`${baseURL}/admin/v1/auth/login`, {
    headers: { origin: baseURL },
    data: { username, password },
  });
  expect(response.status()).toBe(200);
  const body: unknown = await response.json();
  if (
    typeof body !== "object"
    || body === null
    || !("csrf_token" in body)
    || typeof body.csrf_token !== "string"
  ) {
    throw new Error("login response invalid");
  }
  return body.csrf_token;
}

async function expectNoSeriousAccessibilityViolations(page: Page) {
  const result = await new AxeBuilder({ page }).analyze();
  const serious = result.violations.filter(
    (violation) => violation.impact === "serious" || violation.impact === "critical",
  );
  expect(serious.map((violation) => violation.id)).toEqual([]);
}

test.describe.serial("P2a actual P1 browser boundary", () => {
  let adminContext: BrowserContext;
  let adminPage: Page;
  const sensitiveValues: string[] = [adminPassword];
  const consoleMessages: string[] = [];

  test.beforeAll(async ({ browser }) => {
    adminContext = await browser.newContext({ ignoreHTTPSErrors: true });
    adminPage = await adminContext.newPage();
    adminPage.on("console", (message) => { consoleMessages.push(message.text()); });
  });

  test.afterAll(async () => {
    await adminContext.close();
  });

  test("completes bootstrap through first signed snapshot against P1 APIs", async () => {
    const state = await readState();
    sensitiveValues.push(state.bootstrap_token);
    await adminPage.goto("/setup");
    await expect(adminPage.getByRole("heading", { name: "Control Plane 연결 확인" })).toBeVisible();
    await expectNoSeriousAccessibilityViolations(adminPage);
    await adminPage.getByRole("button", { name: "관리자 설정 계속" }).click();
    await expectNoSeriousAccessibilityViolations(adminPage);
    await adminPage.getByLabel("bootstrap token").fill(state.bootstrap_token);
    await adminPage.getByLabel("관리자 사용자 이름").fill("admin");
    await adminPage.getByLabel("관리자 비밀번호").fill(adminPassword);
    const bootstrapResponsePromise = adminPage.waitForResponse(
      (response) => response.url().endsWith("/admin/v1/bootstrap") && response.status() === 201,
    );
    await adminPage.getByRole("button", { name: "최초 관리자 생성" }).click();
    const bootstrapBody: unknown = await (await bootstrapResponsePromise).json();
    if (typeof bootstrapBody === "object" && bootstrapBody !== null && "recovery_codes" in bootstrapBody && Array.isArray(bootstrapBody.recovery_codes)) {
      sensitiveValues.push(...bootstrapBody.recovery_codes.filter((value): value is string => typeof value === "string"));
    }
    await expect(adminPage.getByRole("dialog", { name: "일회용 복구 코드" })).toBeVisible();
    await adminPage.getByRole("button", { name: "복구 코드를 보관했습니다" }).click();

    await adminPage.getByLabel("관리자 사용자 이름").fill("admin");
    await adminPage.getByLabel("관리자 비밀번호").fill(adminPassword);
    await adminPage.getByRole("button", { name: "로그인하고 설정 계속" }).click();

    await adminPage.getByLabel("Provider 이름").fill("vision-primary");
    await adminPage.getByLabel("HTTPS endpoint").fill("https://provider.test/v1/vision");
    await adminPage.getByLabel("Secret 환경변수 이름").fill("VISION_API_KEY");
    await adminPage.getByRole("button", { name: "Provider 저장" }).click();

    await adminPage.getByLabel("정확한 model ID").fill("vendor/text-model");
    await adminPage.getByLabel("Capability 근거").fill("P2a local browser verification");
    await adminPage.getByRole("button", { name: "Non-Vision 모델 저장" }).click();
    await adminPage.getByRole("button", { name: "안전 정책 저장" }).click();

    await adminPage.getByLabel("credential 이름").fill("desktop-agent");
    const credentialResponsePromise = adminPage.waitForResponse(
      (response) => response.url().endsWith("/admin/v1/credentials") && response.status() === 201,
    );
    await adminPage.getByRole("button", { name: "credential 생성" }).click();
    const credentialBody: unknown = await (await credentialResponsePromise).json();
    if (typeof credentialBody === "object" && credentialBody !== null && "credential" in credentialBody && typeof credentialBody.credential === "string") {
      sensitiveValues.push(credentialBody.credential);
    }
    await adminPage.getByRole("button", { name: "확인하고 닫기" }).click();
    await adminPage.getByRole("button", { name: "검증하고 첫 snapshot 발행" }).click();
    await expect(adminPage.getByRole("heading", { name: "온보딩 완료" })).toBeVisible();
    await adminPage.getByRole("link", { name: "Dashboard로 이동" }).click();
    await expect(adminPage.getByRole("heading", { name: "Dashboard" })).toBeVisible();
    await expectNoSeriousAccessibilityViolations(adminPage);

    const browserState = await adminPage.evaluate(() => ({
      html: document.documentElement.outerHTML,
      href: window.location.href,
      local: JSON.stringify(window.localStorage),
      session: JSON.stringify(window.sessionStorage),
    }));
    const retained = `${browserState.html}\n${browserState.href}\n${browserState.local}\n${browserState.session}\n${consoleMessages.join("\n")}`;
    expect(sensitiveValues.some((value) => retained.includes(value)), "sensitive value retained in browser-visible state").toBe(false);
  });

  test("enforces actual P1 role matrix and role-aware UI", async ({ browser }) => {
    const adminCsrf = await loginApi(adminContext, "admin", adminPassword);
    for (const [username, password, role] of [
      ["operator", operatorPassword, "operator"],
      ["viewer", viewerPassword, "viewer"],
    ] as const) {
      const created = await adminContext.request.post(`${baseURL}/admin/v1/users`, {
        headers: { origin: baseURL, "x-csrf-token": adminCsrf },
        data: { username, password, role },
      });
      expect(created.status()).toBe(201);
    }

    const viewerContext = await browser.newContext({ ignoreHTTPSErrors: true });
    const operatorContext = await browser.newContext({ ignoreHTTPSErrors: true });
    try {
      const viewerCsrf = await loginApi(viewerContext, "viewer", viewerPassword);
      const operatorCsrf = await loginApi(operatorContext, "operator", operatorPassword);
      expect((await viewerContext.request.get(`${baseURL}/admin/v1/providers`)).status()).toBe(200);
      expect((await viewerContext.request.post(`${baseURL}/admin/v1/providers`, {
        headers: { origin: baseURL, "x-csrf-token": viewerCsrf },
        data: { name: "viewer-denied", kind: "vision", endpoint: "https://provider.test/v1", secret_ref: { kind: "env", identifier: "VIEWER_KEY" }, enabled: true },
      })).status()).toBe(403);
      expect((await operatorContext.request.get(`${baseURL}/admin/v1/users`)).status()).toBe(403);
      expect((await operatorContext.request.post(`${baseURL}/admin/v1/providers`, {
        headers: { origin: baseURL, "x-csrf-token": operatorCsrf },
        data: { name: "operator-provider", kind: "vision", endpoint: "https://provider.test/v1", secret_ref: { kind: "env", identifier: "OPERATOR_KEY" }, enabled: true },
      })).status()).toBe(201);
      expect((await adminContext.request.get(`${baseURL}/admin/v1/users`)).status()).toBe(200);

      const viewerPage = await viewerContext.newPage();
      await viewerPage.goto(`${baseURL}/providers`);
      await expect(viewerPage.getByRole("heading", { name: "Providers" })).toBeVisible();
      await expect(viewerPage.getByRole("button", { name: "Provider 추가" })).toHaveCount(0);
      await expect(viewerPage.getByRole("link", { name: "Credentials" })).toHaveCount(0);
    } finally {
      await viewerContext.close();
      await operatorContext.close();
    }
  });

  test("keeps deferred routes network inert and passes local accessibility viewports", async () => {
    const requestedPaths: string[] = [];
    adminPage.on("request", (request) => {
      requestedPaths.push(new URL(request.url()).pathname);
    });
    await adminPage.goto("/connections");
    await expect(adminPage.getByText("DEPENDENCY_NOT_READY")).toBeVisible();
    await adminPage.evaluate(() => {
      if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
    });
    for (let attempt = 0; attempt < 12; attempt += 1) {
      await adminPage.keyboard.press("Tab");
      const focused = await adminPage.evaluate(() => (
        document.activeElement instanceof HTMLElement
          ? document.activeElement.textContent.trim()
          : null
      ));
      if (focused === "Test Lab") break;
    }
    expect(await adminPage.evaluate(() => (
      document.activeElement instanceof HTMLElement
        ? document.activeElement.textContent.trim()
        : null
    ))).toBe("Test Lab");
    await adminPage.keyboard.press("Enter");
    await expect(adminPage.getByRole("heading", { name: "Test Lab" })).toBeVisible();
    const forbidden = requestedPaths.filter(
      (path) => path === "/assets" || path.startsWith("/assets/") || path === "/v1/responses",
    );
    expect(forbidden).toEqual([]);
    const allowedAdminRequests = new Set(["/admin/v1/me", "/admin/v1/snapshots"]);
    expect(
      requestedPaths.filter(
        (path) => path.startsWith("/admin/v1/") && !allowedAdminRequests.has(path),
      ),
    ).toEqual([]);
    await expectNoSeriousAccessibilityViolations(adminPage);

    for (const width of [320, 768, 1440]) {
      await adminPage.setViewportSize({ width, height: 900 });
      await adminPage.goto("/providers");
      await expect(adminPage.getByRole("heading", { name: "Providers" })).toBeVisible();
      const overflows = await adminPage.evaluate(
        () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
      );
      expect(overflows, `horizontal overflow at ${String(width)}px`).toBe(false);
    }
  });
});
