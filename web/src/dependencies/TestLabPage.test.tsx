import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TestLabPage } from "./TestLabPage";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
}
function requestUrl(input: RequestInfo | URL): string {
  return typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
}
const image = () => new File([new Uint8Array([137, 80, 78, 71])], "error.png", { type: "image/png" });

it("sends the selected public model and standard reasoning effort", async () => {
  const user = userEvent.setup();
  const fetchMock = vi.fn<typeof fetch>((input) => requestUrl(input).endsWith("/models")
    ? Promise.resolve(jsonResponse([{ model_id: "upstage/solar-pro4" }]))
    : Promise.resolve(jsonResponse({ action: "preview", status: "validated" })));
  vi.stubGlobal("fetch", fetchMock);
  render(<TestLabPage role="operator" csrfToken="csrf-value" />);
  await user.selectOptions(await screen.findByLabelText("공개 모델"), "upstage/solar-pro4");
  await user.selectOptions(screen.getByLabelText("추론 등급"), "high");
  await user.type(screen.getByLabelText("질문"), "이 이미지의 내용을 설명해줘");
  await user.upload(screen.getByLabelText(/질문에 첨부할 이미지/), image());
  fireEvent.submit(screen.getByRole("button", { name: "전체 파이프라인 시험" }).closest("form")!);
  expect(await screen.findByText(/validated/)).toBeInTheDocument();
  const call = fetchMock.mock.calls.find(([input]) => requestUrl(input) === "/admin/v1/test-lab/preview");
  const body = JSON.parse(String((call?.[1] as RequestInit).body));
  expect(body.routing_profile_id).toBeUndefined();
  expect(body.target_model).toBe("upstage/solar-pro4");
  expect(body.reasoning_effort).toBe("high");
});

it("sends OmniRoute-specific model and reasoning settings", async () => {
  const user = userEvent.setup();
  const fetchMock = vi.fn<typeof fetch>((input) => requestUrl(input).endsWith("/models")
    ? Promise.resolve(jsonResponse([{ model_id: "upstage/solar-pro4" }, { model_id: "openai/gpt-5" }]))
    : Promise.resolve(jsonResponse({ action: "omniroute", status: "validated" })));
  vi.stubGlobal("fetch", fetchMock);
  render(<TestLabPage role="operator" csrfToken="csrf-value" />);
  await user.selectOptions(await screen.findByLabelText("OmniRoute 공개 모델"), "openai/gpt-5");
  await user.selectOptions(screen.getByLabelText("OmniRoute 추론 등급"), "high");
  await user.type(screen.getByLabelText("질문"), "OmniRoute 설정 시험");
  await user.upload(screen.getByLabelText(/질문에 첨부할 이미지/), image());
  await user.type(screen.getByLabelText("Media Bridge 접근 키 원문"), "mbc-test-key");
  fireEvent.submit(screen.getByRole("button", { name: "OmniRoute 전체 흐름 시험" }).closest("form")!);
  expect(await screen.findByText(/omniroute/)).toBeInTheDocument();
  const call = fetchMock.mock.calls.find(([input]) => requestUrl(input) === "/admin/v1/test-lab/run");
  const body = JSON.parse(String((call?.[1] as RequestInit).body));
  expect(body.target_model).toBe("openai/gpt-5");
  expect(body.reasoning_effort).toBe("high");
});

it("keeps omitted model distinct from auto", async () => {
  const user = userEvent.setup();
  const fetchMock = vi.fn<typeof fetch>((input) => requestUrl(input).endsWith("/models")
    ? Promise.resolve(jsonResponse([]))
    : Promise.resolve(jsonResponse({ result: "ok" })));
  vi.stubGlobal("fetch", fetchMock);
  render(<TestLabPage role="operator" csrfToken="csrf-value" />);
  expect(await screen.findByLabelText("공개 모델")).toBeInTheDocument();
  expect(screen.getByLabelText("공개 모델")).toHaveValue("");
  await user.selectOptions(screen.getByLabelText("공개 모델"), "auto");
  expect(screen.getByLabelText("공개 모델")).toHaveValue("auto");
});

it("clears the result after its TTL", async () => {
  const user = userEvent.setup();
  vi.stubGlobal("fetch", vi.fn<typeof fetch>((input) => requestUrl(input).endsWith("/models")
    ? Promise.resolve(jsonResponse([]))
    : Promise.resolve(jsonResponse({ result: "TTL RESULT" }))));
  render(<TestLabPage role="operator" csrfToken="csrf-value" resultTtlMs={100} />);
  await user.type(screen.getByLabelText("질문"), "expire me");
  await user.upload(screen.getByLabelText(/질문에 첨부할 이미지/), image());
  fireEvent.submit(screen.getByRole("button", { name: "전체 파이프라인 시험" }).closest("form")!);
  expect(await screen.findByText(/TTL RESULT/)).toBeInTheDocument();
  await waitFor(() => expect(screen.queryByText(/TTL RESULT/)).not.toBeInTheDocument(), { timeout: 1000 });
});

it("hides test controls from viewer", () => {
  render(<TestLabPage role="viewer" csrfToken="csrf-value" />);
  expect(screen.getByText(/viewer는 시험을 실행할 수 없습니다/)).toBeInTheDocument();
  expect(screen.queryByLabelText(/질문에 첨부할 이미지/)).not.toBeInTheDocument();
});
