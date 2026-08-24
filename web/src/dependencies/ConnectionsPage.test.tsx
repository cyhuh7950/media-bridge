import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ConnectionsPage } from "./ConnectionsPage";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function requestUrl(input: RequestInfo | URL): string {
  if (typeof input === "string") return input;
  return input instanceof URL ? input.href : input.url;
}

it("uses only same-origin Admin API, clears the Secret reference, and exposes role actions", async () => {
  const user = userEvent.setup();
  const fetchMock = vi.fn<typeof fetch>((input, init) => {
    const url = requestUrl(input);
    expect(url.startsWith("/admin/v1/")).toBe(true);
    if (url === "/admin/v1/connections" && (init?.method ?? "GET") === "POST") {
      return Promise.resolve(jsonResponse({ id: "connection-1", status: "untested" }, 201));
    }
    return Promise.resolve(jsonResponse([
      {
        id: "connection-1",
        name: "primary",
        gateway_url: "https://gateway.example.test",
        credential_secret_ref: { kind: "env", identifier: "MED***IAL" },
        status: "ready",
        last_success_at: "2026-08-25T04:00:00+00:00",
      },
    ]));
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<ConnectionsPage role="admin" csrfToken="csrf-value" />);

  expect(await screen.findByText("primary")).toBeInTheDocument();
  await user.type(screen.getByLabelText("이름"), "secondary");
  await user.type(screen.getByLabelText("Gateway HTTPS URL"), "https://gateway.example.test");
  const secretInput = screen.getByLabelText("Credential 환경변수 이름");
  await user.type(secretInput, "MEDIA_BRIDGE_GATEWAY_CREDENTIAL");
  await user.click(screen.getByRole("button", { name: "Connection 추가" }));

  await waitFor(() => { expect(secretInput).toHaveValue(""); });
  const createCall = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
  expect(createCall?.[0]).toBe("/admin/v1/connections");
  expect(document.body.textContent).not.toContain("MEDIA_BRIDGE_GATEWAY_CREDENTIAL");
  expect(screen.getByRole("button", { name: "연결 시험" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "폐기" })).toBeInTheDocument();
});


it("keeps viewer read-only at the UI while loading actual API state", async () => {
  vi.stubGlobal("fetch", vi.fn<typeof fetch>(() => Promise.resolve(jsonResponse([]))));
  render(<ConnectionsPage role="viewer" csrfToken="csrf-value" />);

  expect(await screen.findByText(/viewer는 Connection을 읽기만/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Connection 추가" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "연결 시험" })).not.toBeInTheDocument();
});
