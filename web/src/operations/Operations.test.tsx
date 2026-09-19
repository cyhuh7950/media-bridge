import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AuditEventsPage } from "./AuditEventsPage";
import { CredentialsPage } from "./CredentialsPage";
import { DashboardPage } from "./DashboardPage";
import { ProvidersPage } from "./ProvidersPage";
import { SnapshotsPage } from "./SnapshotsPage";
import { SystemPage } from "./SystemPage";

function jsonResponse(body: object, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function requestPath(input: Parameters<typeof fetch>[0]): string {
  if (typeof input === "string") return input;
  if (input instanceof URL) return input.toString();
  return input.url;
}

it("builds dashboard status only from current P1 API responses", async () => {
  const responses = new Map<string, object>([
    ["/admin/v1/health", { status: "ok" }],
    ["/admin/v1/providers", [{ id: "p1" }]],
    ["/admin/v1/models", [{ id: "m1" }, { id: "m2" }]],
    ["/admin/v1/policies", [{ id: "policy1" }]],
    ["/admin/v1/snapshots", [{ version: 3 }]],
    ["/admin/v1/events", [{ event_type: "snapshot_applied" }]],
  ]);
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>((input) => {
      const body = responses.get(requestPath(input));
      return body ? Promise.resolve(jsonResponse(body)) : Promise.reject(new Error("unexpected"));
    }),
  );

  render(<DashboardPage role="admin" />);

  expect(await screen.findByText("3")).toBeInTheDocument();
  expect(screen.getByText("2")).toBeInTheDocument();
  expect(screen.getByText("snapshot_applied")).toBeInTheDocument();
  expect(document.body.textContent).not.toMatch(/demo|sample|가짜/i);
});

it("renders persisted provider references but no write controls for a viewer", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse([
        {
          id: "provider-1",
          name: "vision-primary",
          kind: "vision",
          endpoint: "https://provider.test/v1",
          secret_ref: { kind: "env", identifier: "VISION_API_KEY" },
          enabled: true,
        },
      ]),
    ),
  );

  render(<ProvidersPage role="viewer" csrfToken={null} />);

  expect(await screen.findByText("vision-primary")).toBeInTheDocument();
  expect(screen.getByText("환경변수: VISION_API_KEY")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Provider 추가" })).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Provider Secret 원문")).not.toBeInTheDocument();
});

it("does not expose the internal DB provider secret identifier", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse([{ id: "provider-1", name: "llm-primary", kind: "llm", endpoint: "https://llm.test/v1", secret_ref: { kind: "db", identifier: "provider_api_key" }, enabled: true }]),
    ),
  );

  render(<ProvidersPage role="viewer" csrfToken={null} />);

  expect(await screen.findByText("DB에 저장된 API 키")).toBeInTheDocument();
  expect(screen.queryByText("DB: provider_api_key")).not.toBeInTheDocument();
});

it("uses the standard provider list actions with register/edit dialog and bulk delete", async () => {
  const providers = [
    {
      id: "provider-1",
      name: "vision-primary",
      kind: "analysis",
      endpoint: "https://provider.test/v1",
      secret_ref: { kind: "db", identifier: "provider_api_key" },
      enabled: true,
    },
    {
      id: "provider-2",
      name: "llm-primary",
      kind: "llm",
      endpoint: "https://llm.test/v1",
      secret_ref: { kind: "env", identifier: "LLM_API_KEY" },
      enabled: true,
    },
  ];
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn<typeof fetch>((input, init) => {
    const path = requestPath(input);
    const method = init?.method ?? "GET";
    calls.push(`${method} ${path}`);
    if (method === "GET") return Promise.resolve(jsonResponse(providers));
    return Promise.resolve(new Response(null, { status: 204 }));
  }));
  vi.spyOn(window, "confirm").mockReturnValue(true);
  const user = userEvent.setup();

  render(<ProvidersPage role="admin" csrfToken="csrf-memory-only" />);

  expect(await screen.findByRole("button", { name: "Provider 등록" })).toBeInTheDocument();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  const firstRow = await screen.findByRole("row", { name: /vision-primary/ });
  expect(within(firstRow).getByRole("button", { name: "수정" })).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "Provider 등록" }));
  expect(screen.getByRole("dialog", { name: "Provider 등록" })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "취소" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

  await user.click(within(firstRow).getByRole("button", { name: "수정" }));
  expect(screen.getByRole("dialog", { name: "Provider 수정" })).toBeInTheDocument();
  expect(screen.getByLabelText("Provider 이름")).toHaveValue("vision-primary");
  expect(screen.getByLabelText("Secret 저장 위치")).toHaveValue("DB에 저장된 API 키 사용 중");
  expect(screen.getByLabelText("Secret 저장 위치")).toHaveAttribute("readonly");
  await user.click(screen.getByRole("button", { name: "취소" }));

  await user.click(screen.getByLabelText("vision-primary 선택"));
  await user.click(screen.getByLabelText("llm-primary 선택"));
  await user.click(screen.getByRole("button", { name: /선택 삭제/ }));
  expect(calls).toContain("DELETE /admin/v1/providers/provider-1");
  expect(calls).toContain("DELETE /admin/v1/providers/provider-2");
});

it("shows an issued credential once and clears it on close", async () => {
  const credential = "mbc_selector.operation-secret-marker";
  const fetchMock = vi.fn<typeof fetch>((input, init) => {
    const path = requestPath(input);
    if (path === "/admin/v1/credentials" && (init?.method ?? "GET") === "GET") {
      return Promise.resolve(jsonResponse([]));
    }
    if (path === "/admin/v1/credentials" && init?.method === "POST") {
      return Promise.resolve(jsonResponse({ credential, selector: "selector", name: "agent", scopes: ["assets:write", "mcp:invoke", "responses:invoke"] }, 201));
    }
    return Promise.reject(new Error("unexpected"));
  });
  vi.stubGlobal(
    "fetch",
    fetchMock,
  );
  const user = userEvent.setup();

  render(<CredentialsPage role="admin" csrfToken="csrf-memory-only" />);
  await user.click(await screen.findByRole("button", { name: "접근 키 발급" }));
  await user.type(screen.getByLabelText("접근 키 이름"), "agent");
  await user.click(screen.getByLabelText("Asset 업로드 (assets:write)"));
  await user.click(screen.getByLabelText("Responses 실행 (responses:invoke)"));
  await user.click(screen.getByRole("button", { name: "발급" }));

  expect(await screen.findByText(credential)).toBeInTheDocument();
  const createCall = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
  const createBody = createCall?.[1]?.body;
  expect(typeof createBody).toBe("string");
  if (typeof createBody !== "string") throw new Error("expected JSON request body");
  expect(JSON.parse(createBody)).toMatchObject({
    scopes: ["assets:write", "mcp:invoke", "responses:invoke"],
  });
  await user.click(screen.getByRole("button", { name: "확인하고 닫기" }));
  expect(document.documentElement.outerHTML).not.toContain(credential);
  expect(window.localStorage).toHaveLength(0);
  expect(window.sessionStorage).toHaveLength(0);
});

it("calls snapshot rollback only after explicit confirmation", async () => {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>((input, init) => {
      const path = requestPath(input);
      calls.push(`${init?.method ?? "GET"} ${path}`);
      if ((init?.method ?? "GET") === "GET") {
        return Promise.resolve(jsonResponse([{ version: 4, created_at: "2026-08-24T01:00:00Z" }]));
      }
      return Promise.resolve(jsonResponse({ version: 5 }, 201));
    }),
  );
  const user = userEvent.setup();
  const confirmMock = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);

  render(<SnapshotsPage role="admin" csrfToken="csrf-memory-only" />);
  const row = await screen.findByRole("row", { name: /version 4/i });
  const rollback = within(row).getByRole("button", { name: "이 버전으로 rollback" });
  await user.click(rollback);
  expect(calls.filter((call) => call.startsWith("POST"))).toHaveLength(0);
  await user.click(rollback);
  expect(calls).toContain("POST /admin/v1/snapshots/4/rollback");
  expect(confirmMock).toHaveBeenCalledTimes(2);
});

it("shows audit, operational event, health, and principal from their real endpoints", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>((input) => {
      const path = requestPath(input);
      if (path.endsWith("/audit")) return Promise.resolve(jsonResponse([{ action: "snapshot.published", target_type: "snapshot" }]));
      if (path.endsWith("/events")) return Promise.resolve(jsonResponse([{ event_type: "snapshot_applied", severity: "info" }]));
      if (path.endsWith("/health")) return Promise.resolve(jsonResponse({ status: "ok" }));
      if (path.endsWith("/me")) return Promise.resolve(jsonResponse({ username: "viewer", role: "viewer", csrf_token: "csrf-viewer" }));
      return Promise.reject(new Error("unexpected"));
    }),
  );

  const { unmount } = render(<AuditEventsPage />);
  expect(await screen.findByText("snapshot.published")).toBeInTheDocument();
  expect(screen.getByText("snapshot_applied")).toBeInTheDocument();
  unmount();
  render(<SystemPage />);
  expect(await screen.findAllByText("viewer")).toHaveLength(2);
  expect(screen.getByText("ok")).toBeInTheDocument();
});
