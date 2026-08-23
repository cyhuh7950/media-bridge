import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AdminStep } from "./AdminStep";

function jsonResponse(body: object, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

it("clears bootstrap, password, and recovery values after the one-time dialog closes", async () => {
  const bootstrapMarker = "mbb_selector.bootstrap-browser-marker";
  const passwordMarker = "correct horse battery password-browser-marker";
  const recoveryMarker = "recovery-browser-marker";
  const completed = vi.fn<(username: string, password: string) => Promise<void>>()
    .mockResolvedValue(undefined);
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse({ user_id: "user-1", role: "admin", recovery_codes: [recoveryMarker] }, 201),
    ),
  );
  const user = userEvent.setup();

  render(<AdminStep onComplete={completed} />);
  await user.type(screen.getByLabelText("bootstrap token"), bootstrapMarker);
  await user.type(screen.getByLabelText("관리자 사용자 이름"), "admin");
  await user.type(screen.getByLabelText("관리자 비밀번호"), passwordMarker);
  await user.click(screen.getByRole("button", { name: "최초 관리자 생성" }));

  expect(await screen.findByText(recoveryMarker)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "복구 코드를 보관했습니다" }));
  expect(completed).toHaveBeenCalledWith("admin", passwordMarker);
  expect(document.documentElement.outerHTML).not.toContain(bootstrapMarker);
  expect(document.documentElement.outerHTML).not.toContain(passwordMarker);
  expect(document.documentElement.outerHTML).not.toContain(recoveryMarker);
  expect(window.localStorage).toHaveLength(0);
  expect(window.sessionStorage).toHaveLength(0);
});
