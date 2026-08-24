import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { TestLabPage } from "./TestLabPage";

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

it("previews through same-origin Admin API and keeps downstream off by default", async () => {
  const user = userEvent.setup();
  const fetchMock = vi.fn<typeof fetch>((input) => {
    const url = requestUrl(input);
    expect(url.startsWith("/admin/v1/")).toBe(true);
    if (url === "/admin/v1/connections") {
      return Promise.resolve(jsonResponse([{ id: "connection-1", name: "primary", status: "ready" }]));
    }
    if (url === "/admin/v1/test-lab/preview") {
      return Promise.resolve(jsonResponse({
        action: "converted",
        sanitized_text: "OCR SAFE RESULT",
        original_image_removed: true,
      }));
    }
    return Promise.resolve(jsonResponse({ id: "resp_test", output: [] }));
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<TestLabPage role="operator" csrfToken="csrf-value" />);

  await user.selectOptions(await screen.findByLabelText("Connection"), "connection-1");
  await user.type(screen.getByLabelText("대상 모델"), "text-model");
  await user.type(screen.getByLabelText("사용자 요청"), "이 오류를 설명해줘");
  await user.upload(
    screen.getByLabelText(/이미지 또는 PDF/),
    new File([new Uint8Array([137, 80, 78, 71])], "error.png", { type: "image/png" }),
  );
  const runButton = screen.getByRole("button", { name: "실제 downstream 시험" });
  expect(runButton).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "Preview" }));

  expect(await screen.findByText(/OCR SAFE RESULT/)).toBeInTheDocument();
  expect(fetchMock.mock.calls.some(([input]) => requestUrl(input) === "/admin/v1/test-lab/preview")).toBe(true);
  expect(fetchMock.mock.calls.some(([input]) => requestUrl(input) === "/admin/v1/test-lab/run")).toBe(false);
  expect(screen.getByLabelText(/이미지 또는 PDF/)).toHaveValue("");
  expect(screen.getByLabelText("사용자 요청")).toHaveValue("");

  await user.click(screen.getByRole("button", { name: "결과 지우기" }));
  await waitFor(() => { expect(screen.queryByText(/OCR SAFE RESULT/)).not.toBeInTheDocument(); });
});


it("requires a fresh explicit opt-in for each downstream run", async () => {
  const user = userEvent.setup();
  const fetchMock = vi.fn<typeof fetch>((input) => {
    if (requestUrl(input) === "/admin/v1/connections") {
      return Promise.resolve(jsonResponse([{ id: "connection-1", name: "primary", status: "ready" }]));
    }
    return Promise.resolve(jsonResponse({ id: "resp_test", output: [] }));
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<TestLabPage role="admin" csrfToken="csrf-value" />);

  await user.selectOptions(await screen.findByLabelText("Connection"), "connection-1");
  await user.type(screen.getByLabelText("대상 모델"), "text-model");
  await user.type(screen.getByLabelText("사용자 요청"), "run once");
  await user.upload(
    screen.getByLabelText(/이미지 또는 PDF/),
    new File([new Uint8Array([137, 80, 78, 71])], "error.png", { type: "image/png" }),
  );
  await user.click(screen.getByLabelText(/실제 downstream Provider 호출/));
  const runButton = screen.getByRole("button", { name: "실제 downstream 시험" });
  expect(runButton).toBeEnabled();
  await user.click(runButton);

  await waitFor(() => {
    expect(fetchMock.mock.calls.some(([input]) => requestUrl(input) === "/admin/v1/test-lab/run")).toBe(true);
  });
  expect(screen.getByLabelText(/실제 downstream Provider 호출/)).not.toBeChecked();
  expect(screen.getByRole("button", { name: "실제 downstream 시험" })).toBeDisabled();
});


it("does not expose upload controls to viewer", () => {
  vi.stubGlobal("fetch", vi.fn<typeof fetch>(() => Promise.resolve(jsonResponse([]))));
  render(<TestLabPage role="viewer" csrfToken="csrf-value" />);
  expect(screen.getByText(/viewer는 시험 본문/)).toBeInTheDocument();
  expect(screen.queryByLabelText(/이미지 또는 PDF/)).not.toBeInTheDocument();
});
