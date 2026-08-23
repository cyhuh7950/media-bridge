import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { App } from "./App";

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

it("redirects an anonymous user to login and clears the password after authentication", async () => {
  window.history.replaceState({}, "", "/providers");
  let checkedSession = false;
  const fetchMock = vi.fn<typeof fetch>((input, init) => {
    const path = requestPath(input);
    if (path === "/admin/v1/me" && !checkedSession) {
      checkedSession = true;
      return Promise.resolve(jsonResponse({ error: { code: "unauthorized" } }, 401));
    }
    if (path === "/admin/v1/auth/login" && init?.method === "POST") {
      return Promise.resolve(
        jsonResponse({ username: "admin", role: "admin", csrf_token: "csrf-memory-only" }),
      );
    }
    if (path === "/admin/v1/health") return Promise.resolve(jsonResponse({ status: "ok" }));
    if (path === "/admin/v1/snapshots") return Promise.resolve(jsonResponse([{ version: 1 }]));
    if (["/admin/v1/providers", "/admin/v1/models", "/admin/v1/policies", "/admin/v1/events"].includes(path)) {
      return Promise.resolve(jsonResponse([]));
    }
    return Promise.reject(new Error(`unexpected request: ${path}`));
  });
  vi.stubGlobal("fetch", fetchMock);
  const user = userEvent.setup();
  const passwordMarker = "browser-password-marker";

  render(<App />);

  expect(await screen.findByRole("heading", { name: "Media Bridge 로그인" })).toBeInTheDocument();
  await user.type(screen.getByLabelText("사용자 이름"), "admin");
  await user.type(screen.getByLabelText("비밀번호"), passwordMarker);
  await user.click(screen.getByRole("button", { name: "로그인" }));

  await waitFor(() => {
    expect(screen.getByRole("navigation")).toBeInTheDocument();
  });
  expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
  expect(document.documentElement.outerHTML).not.toContain(passwordMarker);
  expect(document.documentElement.outerHTML).not.toContain("csrf-memory-only");
  expect(window.localStorage).toHaveLength(0);
  expect(window.sessionStorage).toHaveLength(0);
  expect(fetchMock.mock.calls.some(([input]) => requestPath(input) === "/admin/v1/auth/login")).toBe(true);
});
