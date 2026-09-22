import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AuditEventsPage } from "./AuditEventsPage";
import { CredentialsPage } from "./CredentialsPage";
import { DashboardPage } from "./DashboardPage";
import { ProvidersPage } from "./ProvidersPage";
import { PoliciesPage } from "./PoliciesPage";
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

function parseRequestBody(body: BodyInit | null | undefined): Record<string, unknown> | undefined {
  if (typeof body !== "string") return undefined;
  const parsed: unknown = JSON.parse(body);
  return typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)
    ? parsed as Record<string, unknown>
    : undefined;
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

  expect(await screen.findByText("등록됨")).toBeInTheDocument();
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
  expect(screen.queryByLabelText("Secret 저장 위치")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Secret 환경변수 이름")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "취소" }));

  await user.click(screen.getByLabelText("vision-primary 선택"));
  await user.click(screen.getByLabelText("llm-primary 선택"));
  await user.click(screen.getByRole("button", { name: /선택 삭제/ }));
  expect(calls).toContain("DELETE /admin/v1/providers/provider-1");
  expect(calls).toContain("DELETE /admin/v1/providers/provider-2");
});

it("registers an LLM with only server-supported reasoning choices", async () => {
  const calls: Array<{ path: string; method: string; body?: Record<string, unknown> }> = [];
  const fetchMock = vi.fn<typeof fetch>((input, init) => {
    const path = requestPath(input);
    const method = init?.method ?? "GET";
    const body = parseRequestBody(init?.body);
    calls.push({ path, method, body });
    if (path === "/admin/v1/providers" && method === "GET") return Promise.resolve(jsonResponse([]));
    if (path.startsWith("/admin/v1/provider-catalog?kind=")) {
      const kind = new URL(path, window.location.origin).searchParams.get("kind");
      return Promise.resolve(jsonResponse(kind === "llm" ? [{
        provider_id: "upstage-solar",
        display_name: "Upstage Solar",
        kind: "llm",
        protocol: "openai-chat-completions",
        capabilities: ["text"],
        default_endpoint: "https://api.upstage.ai/v1/chat/completions",
        secret_env: "SOLAR_API_KEY",
        default_model_id: "solar-pro4",
      }] : []));
    }
    if (path.startsWith("/admin/v1/provider-reasoning-options?")) {
      return Promise.resolve(jsonResponse({ efforts: ["provider_default", "low", "medium", "high"] }));
    }
    if (path === "/admin/v1/providers" && method === "POST") return Promise.resolve(jsonResponse({ id: "solar" }, 201));
    return Promise.reject(new Error(`unexpected request: ${method} ${path}`));
  });
  vi.stubGlobal("fetch", fetchMock);
  const user = userEvent.setup();

  render(<ProvidersPage role="admin" csrfToken="csrf" />);
  await user.click(await screen.findByRole("button", { name: "Provider 등록" }));
  await user.selectOptions(screen.getByLabelText("Provider 유형"), "llm");
  await user.selectOptions(await screen.findByLabelText("Provider 선택"), "upstage-solar");
  expect(screen.queryByLabelText("Secret 환경변수 이름")).not.toBeInTheDocument();
  const effort = await screen.findByLabelText("추론 등급");
  expect(effort).toHaveValue("provider_default");
  expect(within(effort).getAllByRole("option").map((option) => (option as HTMLOptionElement).value)).toEqual([
    "provider_default", "low", "medium", "high",
  ]);

  await user.selectOptions(effort, "high");
  await user.click(screen.getByRole("button", { name: "등록" }));

  const saved = calls.find((call) => call.method === "POST" && call.path === "/admin/v1/providers");
  expect(saved?.body?.reasoning_effort).toBe("high");
  expect(saved?.body?.secret_ref).toEqual({ kind: "db", identifier: "provider_api_key" });
});

it("hides reasoning for analysis Providers and blocks stale LLM effort after model change", async () => {
  const calls: Array<{ path: string; method: string; body?: Record<string, unknown> }> = [];
  const provider = {
    id: "solar",
    name: "solar",
    kind: "llm",
    catalog_id: "upstage-solar",
    model_id: "solar-pro4",
    endpoint: "https://api.upstage.ai/v1/chat/completions",
    protocol: "openai-chat-completions",
    capabilities: ["text"],
    secret_ref: { kind: "db", identifier: "provider_api_key" },
    reasoning_effort: "high",
    enabled: true,
  };
  const fetchMock = vi.fn<typeof fetch>((input, init) => {
    const path = requestPath(input);
    const method = init?.method ?? "GET";
    const body = parseRequestBody(init?.body);
    calls.push({ path, method, body });
    if (path === "/admin/v1/providers" && method === "GET") return Promise.resolve(jsonResponse([provider]));
    if (path.startsWith("/admin/v1/provider-catalog?kind=")) {
      const kind = new URL(path, window.location.origin).searchParams.get("kind");
      return Promise.resolve(jsonResponse(kind === "llm" ? [{
        provider_id: "upstage-solar",
        display_name: "Upstage Solar",
        kind: "llm",
        protocol: "openai-chat-completions",
        capabilities: ["text"],
        default_endpoint: "https://api.upstage.ai/v1/chat/completions",
        secret_env: "SOLAR_API_KEY",
        default_model_id: "solar-pro4",
      }] : []));
    }
    if (path.startsWith("/admin/v1/provider-reasoning-options?")) {
      const model = new URL(path, window.location.origin).searchParams.get("model_id");
      return Promise.resolve(jsonResponse({ efforts: model === "solar-pro4" ? ["provider_default", "low", "medium", "high"] : ["provider_default"] }));
    }
    if (path === "/admin/v1/providers/solar" && method === "PATCH") return Promise.resolve(jsonResponse(provider));
    return Promise.reject(new Error(`unexpected request: ${method} ${path}`));
  });
  vi.stubGlobal("fetch", fetchMock);
  const user = userEvent.setup();

  render(<ProvidersPage role="admin" csrfToken="csrf" />);
  const row = await screen.findByRole("row", { name: /solar/ });
  await user.click(within(row).getByRole("button", { name: "수정" }));
  const effort = await screen.findByLabelText("추론 등급");
  expect(effort).toHaveValue("high");
  fireEvent.change(screen.getByLabelText("기준 모델 (선택)"), { target: { value: "solar-mini" } });
  expect(screen.getByLabelText("기준 모델 (선택)")).toHaveValue("solar-mini");
  await waitFor(() => {
    expect(calls.filter((call) => call.path.includes("provider-reasoning-options")).at(-1)?.path).toContain("model_id=solar-mini");
  });
  expect(await screen.findByText(/현재 저장된 추론 등급은 이 모델에서 지원되지 않습니다/)).toBeInTheDocument();
  await waitFor(() => {
    expect(within(effort).getAllByRole("option").map((option) => (option as HTMLOptionElement).value)).toEqual([
      "provider_default", "high",
    ]);
  });
  await user.click(screen.getByRole("button", { name: "저장" }));
  expect(calls.some((call) => call.method === "PATCH")).toBe(false);

  await waitFor(() => {
    expect(effort).toBeEnabled();
  });
  await user.selectOptions(effort, "provider_default");
  expect(effort).toHaveValue("provider_default");
  await waitFor(() => {
    expect(screen.getByRole("button", { name: "저장" })).toBeEnabled();
  });
  expect(screen.getByLabelText("Provider 선택")).toHaveValue("upstage-solar");
  await user.click(screen.getByRole("button", { name: "저장" }));
  const updated = calls.find((call) => call.method === "PATCH");
  expect(updated?.body?.reasoning_effort).toBe("provider_default");
  await user.click(await screen.findByRole("button", { name: "Provider 등록" }));
  expect(screen.queryByLabelText("추론 등급")).not.toBeInTheDocument();
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

it("publishes the validated draft and reports a publish error", async () => {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>((input, init) => {
      const path = requestPath(input);
      calls.push(`${init?.method ?? "GET"} ${path}`);
      if ((init?.method ?? "GET") === "GET") return Promise.resolve(jsonResponse([]));
      if (path === "/admin/v1/drafts/validate") return Promise.resolve(jsonResponse({ draft_id: "draft-1" }, 201));
      return Promise.resolve(jsonResponse({ error: { code: "configuration_invalid" } }, 409));
    }),
  );
  const user = userEvent.setup();
  render(<SnapshotsPage role="admin" csrfToken="csrf-memory-only" />);
  await user.click(await screen.findByRole("button", { name: "현재 설정 검증 및 발행" }));
  expect(calls).toContain("POST /admin/v1/drafts/validate");
  expect(calls).toContain("POST /admin/v1/snapshots");
  expect(await screen.findByRole("alert")).toHaveTextContent("configuration_invalid");
});

it("explains an expired CSRF session when publishing", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>((input, init) => {
      if ((init?.method ?? "GET") === "GET") return Promise.resolve(jsonResponse([]));
      return Promise.resolve(jsonResponse({ error: { code: "csrf_rejected" } }, 403));
    }),
  );
  const user = userEvent.setup();
  render(<SnapshotsPage role="admin" csrfToken="expired-token" />);
  await user.click(await screen.findByRole("button", { name: "현재 설정 검증 및 발행" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("로그아웃 후 다시 로그인하세요");
});

it("edits all eight policy controls from the standard dialog", async () => {
  const fetchMock = vi.fn<typeof fetch>((input, init) => {
    const path = requestPath(input);
    if ((init?.method ?? "GET") === "GET") {
      return Promise.resolve(jsonResponse([{ id: "policy-1", name: "기본 미디어 보안 정책", max_files: 4, max_media_bytes: 2097152, max_pdf_pages: 20, allow_url: false, allow_base64: true, allow_asset: true, allow_local_path: false, fail_closed: true }]));
    }
    if (path === "/admin/v1/policies/policy-1") return Promise.resolve(jsonResponse({ id: "policy-1" }));
    return Promise.reject(new Error("unexpected"));
  });
  vi.stubGlobal("fetch", fetchMock);
  const user = userEvent.setup();
  render(<PoliciesPage role="admin" csrfToken="csrf-memory-only" />);
  await user.click(await screen.findByRole("button", { name: "수정" }));
  expect(screen.getByLabelText("최대 파일 수")).toHaveValue(4);
  expect(screen.getByLabelText("최대 미디어 크기 (바이트)")).toHaveValue(2097152);
  expect(screen.getByLabelText("최대 PDF 페이지")).toHaveValue(20);
  expect(screen.getByLabelText("URL 입력")).not.toBeChecked();
  expect(screen.getByLabelText("Base64 입력")).toBeChecked();
  expect(screen.getByLabelText("Asset 입력")).toBeChecked();
  expect(screen.getByLabelText("로컬 경로")).not.toBeChecked();
  expect(screen.getByLabelText("Fail-closed")).toBeChecked();
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
