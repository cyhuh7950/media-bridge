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
  await screen.findAllByRole("option", { name: "upstage/solar-pro4" });
  await user.selectOptions(screen.getAllByLabelText("공개 모델")[0]!, "upstage/solar-pro4");
  await user.selectOptions(screen.getAllByLabelText("추론 등급")[0]!, "high");
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

it("sends external-client model and reasoning settings", async () => {
  const user = userEvent.setup();
  const fetchMock = vi.fn<typeof fetch>((input) => requestUrl(input).endsWith("/models")
    ? Promise.resolve(jsonResponse([{ model_id: "upstage/solar-pro4" }, { model_id: "openai/gpt-5" }]))
    : Promise.resolve(jsonResponse({ action: "external", status: "validated" })));
  vi.stubGlobal("fetch", fetchMock);
  render(<TestLabPage role="operator" csrfToken="csrf-value" />);
  await screen.findAllByRole("option", { name: "openai/gpt-5" });
  await user.selectOptions(screen.getAllByLabelText("공개 모델")[1]!, "openai/gpt-5");
  await user.selectOptions(screen.getAllByLabelText("추론 등급")[1]!, "high");
  await user.type(screen.getByLabelText("질문"), "외부 클라이언트 설정 시험");
  await user.upload(screen.getByLabelText(/질문에 첨부할 이미지/), image());
  await user.type(screen.getByLabelText("Media Bridge 접근 키 원문"), "mbc-test-key");
  fireEvent.submit(screen.getByRole("button", { name: "외부 클라이언트 전체 흐름 시험" }).closest("form")!);
  expect(await screen.findByText(/external/)).toBeInTheDocument();
  const call = fetchMock.mock.calls.find(([input]) => requestUrl(input) === "/admin/v1/test-lab/run");
  const body = JSON.parse(String((call?.[1] as RequestInit).body));
  expect(body.target_model).toBe("openai/gpt-5");
  expect(body.reasoning_effort).toBe("high");
});

it.each([
  { name: "미지정 모델은 Gateway 기본값을 그대로 사용한다", selected: "", expected: undefined },
  { name: "auto는 Gateway 자동 선택 값으로 전달한다", selected: "auto", expected: "auto" },
])("$name", async ({ selected, expected }) => {
  const user = userEvent.setup();
  const fetchMock = vi.fn<typeof fetch>((input) => requestUrl(input).endsWith("/models")
    ? Promise.resolve(jsonResponse([{ model_id: "vendor/public-model" }]))
    : Promise.resolve(jsonResponse({ result: "ok" })));
  vi.stubGlobal("fetch", fetchMock);
  render(<TestLabPage role="operator" csrfToken="csrf-value" />);
  const modelSelect = screen.getAllByLabelText("공개 모델")[1]!;
  await screen.findAllByRole("option", { name: "vendor/public-model" });
  if (selected) await user.selectOptions(modelSelect, selected);
  await user.type(screen.getByLabelText("질문"), "모델 라우팅 시험");
  await user.upload(screen.getByLabelText(/질문에 첨부할 이미지/), image());
  await user.type(screen.getByLabelText("Media Bridge 접근 키 원문"), "mbc-test-key");
  fireEvent.submit(screen.getByRole("button", { name: "외부 클라이언트 전체 흐름 시험" }).closest("form")!);
  await screen.findByText(/시험 결과/);
  const call = fetchMock.mock.calls.find(([input]) => requestUrl(input) === "/admin/v1/test-lab/run");
  const body = JSON.parse(String((call?.[1] as RequestInit).body));
  expect(body.target_model).toBe(expected);
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
