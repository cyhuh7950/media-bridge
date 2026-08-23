import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AuthProvider, useAuth } from "./AuthProvider";
import { RequireRole } from "./RequireRole";

function jsonResponse(body: object, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function AuthProbe() {
  const auth = useAuth();
  if (auth.status === "loading") return <p>loading</p>;
  if (auth.status === "anonymous") {
    return <button onClick={() => void auth.login("admin", "test-value")}>login</button>;
  }
  return (
    <>
      <p>{auth.principal.username}:{auth.principal.role}</p>
      <RequireRole allow={["admin"]}><button>admin action</button></RequireRole>
    </>
  );
}

describe("AuthProvider", () => {
  it("loads the current P1 session and enforces the route role in the UI", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ username: "viewer", role: "viewer" })),
    );

    render(<AuthProvider><AuthProbe /></AuthProvider>);

    expect(await screen.findByText("viewer:viewer")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "admin action" })).not.toBeInTheDocument();
    expect(screen.getByText("권한이 없습니다.")).toBeInTheDocument();
  });

  it("keeps the CSRF token in memory after login without browser storage", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ error: { code: "unauthorized" } }, 401))
      .mockResolvedValueOnce(
        jsonResponse({ username: "admin", role: "admin", csrf_token: "csrf-memory-only" }),
      );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<AuthProvider><AuthProbe /></AuthProvider>);
    await user.click(await screen.findByRole("button", { name: "login" }));

    await waitFor(() => expect(screen.getByText("admin:admin")).toBeInTheDocument());
    expect(window.localStorage).toHaveLength(0);
    expect(window.sessionStorage).toHaveLength(0);
    expect(document.documentElement.outerHTML).not.toContain("csrf-memory-only");
  });
});
