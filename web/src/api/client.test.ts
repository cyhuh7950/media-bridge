import { adminRequest, SafeApiError } from "./client";

function jsonResponse(body: object, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("adminRequest", () => {
  it("calls only the same-origin admin API with the session cookie", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ username: "viewer", role: "viewer" }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await adminRequest<{ username: string; role: string }>("/me");

    expect(result).toEqual({ username: "viewer", role: "viewer" });
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock).toHaveBeenCalledWith(
      "/admin/v1/me",
      expect.objectContaining({ credentials: "include" }),
    );
  });

  it.each(["https://internal.test/me", "//internal.test/me", "/assets", "/v1/responses"])(
    "rejects a non-admin path before network access: %s",
    async (path) => {
      const fetchMock = vi.fn();
      vi.stubGlobal("fetch", fetchMock);

      await expect(adminRequest(path)).rejects.toMatchObject({
        code: "invalid_admin_path",
      });
      expect(fetchMock).not.toHaveBeenCalled();
    },
  );

  it("reduces 401 and 403 responses to a safe code without retaining the body", async () => {
    const marker = "browser-secret-marker";
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(
          { error: { code: "forbidden", internal_detail: marker } },
          403,
        ),
      ),
    );

    const failure = await adminRequest("/users").catch((error: unknown) => error);

    expect(failure).toBeInstanceOf(SafeApiError);
    expect(failure).toMatchObject({ status: 403, code: "forbidden" });
    expect(JSON.stringify(failure)).not.toContain(marker);
  });

  it("adds CSRF only to an explicit state-changing request", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({}, 201));
    vi.stubGlobal("fetch", fetchMock);

    await adminRequest("/providers", {
      method: "POST",
      csrfToken: "csrf-test-value",
      body: { name: "provider" },
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "/admin/v1/providers",
      expect.objectContaining({
        headers: expect.objectContaining({ "x-csrf-token": "csrf-test-value" }),
      }),
    );
  });
});
