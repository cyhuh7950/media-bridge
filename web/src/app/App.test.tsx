import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { App } from "./App";

function jsonResponse(body: object, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

it("redirects an anonymous user to login and clears the password after authentication", async () => {
  window.history.replaceState({}, "", "/providers");
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce(jsonResponse({ error: { code: "unauthorized" } }, 401))
    .mockResolvedValueOnce(
      jsonResponse({ username: "admin", role: "admin", csrf_token: "csrf-memory-only" }),
    );
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
  expect(screen.getByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
  expect(document.documentElement.outerHTML).not.toContain(passwordMarker);
  expect(document.documentElement.outerHTML).not.toContain("csrf-memory-only");
  expect(window.localStorage).toHaveLength(0);
  expect(window.sessionStorage).toHaveLength(0);
  expect(fetchMock.mock.calls[1]?.[0]).toBe("/admin/v1/auth/login");
});
