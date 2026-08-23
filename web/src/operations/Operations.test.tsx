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

  render(<DashboardPage />);

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
  expect(screen.getByText("env: VISION_API_KEY")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Provider 추가" })).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Provider Secret 원문")).not.toBeInTheDocument();
});

it("shows an issued credential once and clears it on close", async () => {
  const credential = "mbc_selector.operation-secret-marker";
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>((input, init) => {
      const path = requestPath(input);
      if (path === "/admin/v1/credentials" && (init?.method ?? "GET") === "GET") {
        return Promise.resolve(jsonResponse([]));
      }
      if (path === "/admin/v1/credentials" && init?.method === "POST") {
        return Promise.resolve(jsonResponse({ credential, selector: "selector", name: "agent", scopes: ["mcp:invoke"] }, 201));
      }
      return Promise.reject(new Error("unexpected"));
    }),
  );
  const user = userEvent.setup();

  render(<CredentialsPage role="admin" csrfToken="csrf-memory-only" />);
  await user.type(await screen.findByLabelText("credential 이름"), "agent");
  await user.click(screen.getByRole("button", { name: "접근 credential 생성" }));

  expect(await screen.findByText(credential)).toBeInTheDocument();
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
      if (path.endsWith("/me")) return Promise.resolve(jsonResponse({ username: "viewer", role: "viewer" }));
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
