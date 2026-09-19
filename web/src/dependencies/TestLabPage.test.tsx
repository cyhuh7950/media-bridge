import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { TestLabPage } from "./TestLabPage";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

function requestUrl(input: RequestInfo | URL): string {
  if (typeof input === "string") return input;
  return input instanceof URL ? input.href : input.url;
}

const image = () => new File([new Uint8Array([137, 80, 78, 71])], "error.png", { type: "image/png" });

it("runs Preview with only Preview inputs and never sends downstream credentials", async () => {
  const user = userEvent.setup();
  const fetchMock = vi.fn<typeof fetch>(() => Promise.resolve(jsonResponse({ sanitized_text: "PREVIEW RESULT" })));
  vi.stubGlobal("fetch", fetchMock);
  render(<TestLabPage role="operator" csrfToken="csrf-value" />);

  await user.type(screen.getByLabelText("Preview 테스트 대상 모델"), "text-model");
  await user.type(screen.getByLabelText("Preview 사용자 요청"), "이 오류를 설명해줘");
  await user.upload(screen.getByLabelText("Preview 이미지 또는 PDF · 최대 2 MiB"), image());
  const previewForm = screen.getByRole("button", { name: "Preview 실행" }).closest("form");
  if (previewForm === null) throw new Error("preview form is unavailable");
  fireEvent.submit(previewForm);

  expect(await screen.findByText(/PREVIEW RESULT/)).toBeInTheDocument();
  const call = fetchMock.mock.calls.find(([input]) => requestUrl(input) === "/admin/v1/test-lab/preview");
  const body = JSON.parse(String((call?.[1] as RequestInit).body));
  expect(body).not.toHaveProperty("gateway_url");
  expect(body).not.toHaveProperty("api_key");
});

it("runs downstream with its own endpoint, key, model, request, and file inputs", async () => {
  const user = userEvent.setup();
  const fetchMock = vi.fn<typeof fetch>(() => Promise.resolve(jsonResponse({ id: "resp_test", output: [] })));
  vi.stubGlobal("fetch", fetchMock);
  render(<TestLabPage role="admin" csrfToken="csrf-value" />);

  await user.type(screen.getByLabelText("downstream API endpoint"), "https://gateway.example/v1");
  await user.type(screen.getByLabelText("downstream API 키"), "test-key");
  await user.type(screen.getByLabelText("downstream 대상 모델"), "text-model");
  await user.type(screen.getByLabelText("downstream 사용자 요청"), "run once");
  await user.upload(screen.getByLabelText("downstream 이미지 또는 PDF · 최대 2 MiB"), image());
  const downstreamForm = screen.getByRole("button", { name: "downstream 테스트 실행" }).closest("form");
  if (downstreamForm === null) throw new Error("downstream form is unavailable");
  fireEvent.submit(downstreamForm);

  await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => requestUrl(input) === "/admin/v1/test-lab/run")).toBe(true));
  const call = fetchMock.mock.calls.find(([input]) => requestUrl(input) === "/admin/v1/test-lab/run");
  const body = JSON.parse(String((call?.[1] as RequestInit).body));
  expect(body.gateway_url).toBe("https://gateway.example/v1");
  expect(body.api_key).toBe("test-key");
});

it("removes the transient result after its TTL", async () => {
  const user = userEvent.setup();
  vi.stubGlobal("fetch", vi.fn<typeof fetch>(() => Promise.resolve(jsonResponse({ sanitized_text: "TTL RESULT" }))));
  render(<TestLabPage role="operator" csrfToken="csrf-value" resultTtlMs={100} />);
  await user.type(screen.getByLabelText("Preview 테스트 대상 모델"), "text-model");
  await user.type(screen.getByLabelText("Preview 사용자 요청"), "expire me");
  await user.upload(screen.getByLabelText("Preview 이미지 또는 PDF · 최대 2 MiB"), image());
  const previewForm = screen.getByRole("button", { name: "Preview 실행" }).closest("form");
  if (previewForm === null) throw new Error("preview form is unavailable");
  fireEvent.submit(previewForm);
  expect(await screen.findByText(/TTL RESULT/)).toBeInTheDocument();
  await waitFor(() => expect(screen.queryByText(/TTL RESULT/)).not.toBeInTheDocument(), { timeout: 1_000 });
});

it("does not expose test controls to viewer", () => {
  vi.stubGlobal("fetch", vi.fn<typeof fetch>(() => Promise.resolve(jsonResponse([]))));
  render(<TestLabPage role="viewer" csrfToken="csrf-value" />);
  expect(screen.getByText(/viewer는 시험 본문/)).toBeInTheDocument();
  expect(screen.queryByLabelText(/이미지 또는 PDF/)).not.toBeInTheDocument();
});
