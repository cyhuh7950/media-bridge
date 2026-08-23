import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import {
  deriveOnboardingStep,
  OnboardingWorkflow,
  type OnboardingInventory,
} from "./OnboardingShell";

function jsonResponse(body: object, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

const completeInventory: OnboardingInventory = {
  providers: [{ id: "provider-1" }],
  models: [{ id: "model-1" }],
  policies: [{ id: "policy-1" }],
  credentials: [{ selector: "credential-1" }],
  snapshots: [],
};

it("derives resumable progress only from persisted P1 API resources", () => {
  expect(deriveOnboardingStep({ ...completeInventory, providers: [] })).toBe("provider");
  expect(deriveOnboardingStep({ ...completeInventory, models: [] })).toBe("model");
  expect(deriveOnboardingStep({ ...completeInventory, policies: [] })).toBe("policy");
  expect(deriveOnboardingStep({ ...completeInventory, credentials: [] })).toBe("credential");
  expect(deriveOnboardingStep(completeInventory)).toBe("publish");
  expect(
    deriveOnboardingStep({ ...completeInventory, snapshots: [{ version: 1 }] }),
  ).toBe("complete");
});

it("does not publish when P1 draft validation fails", async () => {
  const requests: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>(async (input, init) => {
      const path = String(input);
      requests.push(`${init?.method ?? "GET"} ${path}`);
      if (path.endsWith("/providers")) return jsonResponse(completeInventory.providers);
      if (path.endsWith("/models")) return jsonResponse(completeInventory.models);
      if (path.endsWith("/policies")) return jsonResponse(completeInventory.policies);
      if (path.endsWith("/credentials")) return jsonResponse(completeInventory.credentials);
      if (path.endsWith("/snapshots")) return jsonResponse([]);
      if (path.endsWith("/drafts/validate")) {
        return jsonResponse({ error: { code: "configuration_incomplete" } }, 409);
      }
      throw new Error(`unexpected request: ${path}`);
    }),
  );
  const user = userEvent.setup();

  render(<OnboardingWorkflow csrfToken="csrf-memory-only" />);

  expect(await screen.findByRole("heading", { name: "설정 검증 및 발행" })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "검증하고 첫 snapshot 발행" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("설정을 발행할 수 없습니다");
  expect(requests).not.toContain("POST /admin/v1/snapshots");
});

it("shows a client credential once and removes it from DOM and storage on close", async () => {
  const marker = "mbc_selector.raw-browser-secret-marker";
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>(async (input, init) => {
      const path = String(input);
      if (path.endsWith("/providers")) return jsonResponse(completeInventory.providers);
      if (path.endsWith("/models")) return jsonResponse(completeInventory.models);
      if (path.endsWith("/policies")) return jsonResponse(completeInventory.policies);
      if (path.endsWith("/credentials") && (init?.method ?? "GET") === "GET") {
        return jsonResponse([]);
      }
      if (path.endsWith("/credentials") && init?.method === "POST") {
        return jsonResponse(
          { credential: marker, selector: "selector", name: "desktop-agent", scopes: ["mcp:invoke"] },
          201,
        );
      }
      if (path.endsWith("/snapshots")) return jsonResponse([]);
      throw new Error(`unexpected request: ${path}`);
    }),
  );
  const user = userEvent.setup();

  render(<OnboardingWorkflow csrfToken="csrf-memory-only" />);
  expect(await screen.findByRole("heading", { name: "접근 credential 생성" })).toBeInTheDocument();
  await user.type(screen.getByLabelText("credential 이름"), "desktop-agent");
  await user.click(screen.getByRole("button", { name: "credential 생성" }));

  expect(await screen.findByText(marker)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "확인하고 닫기" }));
  expect(document.documentElement.outerHTML).not.toContain(marker);
  expect(window.localStorage).toHaveLength(0);
  expect(window.sessionStorage).toHaveLength(0);
});
