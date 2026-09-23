import { useEffect, useRef, useState, type SyntheticEvent } from "react";
import { adminRequest } from "../api/client";
import type { OperationsProps } from "../operations/operationTypes";
import { textField } from "../operations/operationTypes";

const RESULT_TTL_MS = 10 * 60 * 1000;
const MAX_MEDIA_BYTES = 2 * 1024 * 1024;
const DEFAULT_GATEWAY_ENDPOINT = "https://media-bridge-gateway.sinsan.kr";

async function toBase64(file: File): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += 32768) binary += String.fromCharCode(...bytes.subarray(offset, offset + 32768));
  return btoa(binary);
}
function resultRecord(value: unknown): Record<string, unknown> { if (typeof value !== "object" || value === null) throw new Error("invalid response"); return value as Record<string, unknown>; }
interface TestLabPageProps extends OperationsProps { resultTtlMs?: number; }
type PublicModel = { model_id: string };
type ResultSource = "full" | "external";

export function TestLabPage({ role, csrfToken, resultTtlMs = RESULT_TTL_MS }: TestLabPageProps) {
  const [request, setRequest] = useState("");
  const [media, setMedia] = useState<File | null>(null);
  const [publicModels, setPublicModels] = useState<PublicModel[]>([]);
  const [targetModel, setTargetModel] = useState("");
  const [reasoningEffort, setReasoningEffort] = useState("provider_default");
  const [externalTargetModel, setExternalTargetModel] = useState("");
  const [externalReasoningEffort, setExternalReasoningEffort] = useState("provider_default");
  const [externalEndpoint, setExternalEndpoint] = useState(DEFAULT_GATEWAY_ENDPOINT);
  const [externalApiKey, setExternalApiKey] = useState("");
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [resultSource, setResultSource] = useState<ResultSource | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const writable = role !== "viewer" && csrfToken !== null;

  useEffect(() => {
    let active = true;
    void adminRequest<Record<string, unknown>[]>("/models").then((models) => {
      if (active) setPublicModels(models.map((model) => ({ model_id: textField(model, "model_id") })));
    }).catch(() => { if (active) setPublicModels([]); });
    return () => { active = false; };
  }, []);
  useEffect(() => {
    if (result === null) return;
    const timer = window.setTimeout(() => { setResult(null); setResultSource(null); setRequest(""); setMedia(null); if (fileInput.current) fileInput.current.value = ""; }, resultTtlMs);
    return () => { window.clearTimeout(timer); };
  }, [result, resultTtlMs]);
  function clearResult() { setResult(null); setResultSource(null); setRequest(""); setMedia(null); if (fileInput.current) fileInput.current.value = ""; }
  async function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!writable || media === null || media.size < 1 || media.size > MAX_MEDIA_BYTES) { setError("입력값을 확인하세요."); return; }
    setError(null); setResult(null); setResultSource(null);
    try { const response = await adminRequest<unknown>("/test-lab/preview", { method: "POST", csrfToken, body: { target_model: targetModel || undefined, reasoning_effort: reasoningEffort, conversion_profile: "generic", user_request: request, media_type: media.type === "application/pdf" ? "pdf" : "image", filename: media.name, declared_mime: media.type, media_base64: await toBase64(media) } }); setResult(resultRecord(response)); setResultSource("full"); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "upstream_or_downstream_failed"); }
  }
  async function submitExternal(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    const missing: string[] = [];
    if (media === null) missing.push("파일");
    if (!externalEndpoint) missing.push("Media Bridge endpoint");
    if (!externalApiKey) missing.push("접근 키 원문");
    if (media !== null && (media.size < 1 || media.size > MAX_MEDIA_BYTES)) missing.push("파일 크기");
    if (missing.length > 0) { setError("입력값을 확인하세요: " + missing.join(", ")); return; }
    if (!writable || csrfToken === null || media === null) return;
    setError(null); setResult(null); setResultSource(null);
    try { const response = await adminRequest<unknown>("/test-lab/run", { method: "POST", csrfToken, body: { target_model: externalTargetModel || undefined, reasoning_effort: externalReasoningEffort, gateway_url: externalEndpoint, api_key: externalApiKey, conversion_profile: "generic", user_request: request, media_type: media.type === "application/pdf" ? "pdf" : "image", filename: media.name, declared_mime: media.type, media_base64: await toBase64(media), execute_downstream: true } }); setResult(resultRecord(response)); setResultSource("external"); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "external_media_bridge_failed"); }
  }
  if (!writable) return <section aria-labelledby="test-lab-title"><h1 id="test-lab-title">테스트 랩</h1><p>viewer는 시험을 실행할 수 없습니다.</p></section>;
  return <section aria-labelledby="test-lab-title"><h1 id="test-lab-title">테스트 랩</h1><p>선택한 공개 모델과 추론 등급으로 upstream부터 downstream까지 실행하고 결과를 확인합니다.</p><section aria-labelledby="deployment-endpoints-title" className="result-panel"><h2 id="deployment-endpoints-title">배포형 Media Bridge API endpoint</h2><p>기본 주소: <code>{DEFAULT_GATEWAY_ENDPOINT}</code></p><ul><li>OpenAI Responses API: <code>{DEFAULT_GATEWAY_ENDPOINT}/v1/responses</code></li><li>OpenAI Chat Completions: <code>{DEFAULT_GATEWAY_ENDPOINT}/v1/chat/completions</code></li><li>모델 조회: <code>{DEFAULT_GATEWAY_ENDPOINT}/v1/models</code></li><li>MCP: <code>{DEFAULT_GATEWAY_ENDPOINT}/mcp</code></li><li>Asset 업로드: <code>{DEFAULT_GATEWAY_ENDPOINT}/assets</code></li></ul></section><section aria-labelledby="full-test-title" className="result-panel"><h2 id="full-test-title">전체 파이프라인 시험</h2><p>공개 모델과 추론 등급을 선택하면 Gateway를 통해 시험합니다.</p><form className="form-grid compact-form" onSubmit={(event) => { void submit(event); }}><label htmlFor="test-model">공개 모델</label><select id="test-model" value={targetModel} onChange={(event) => { setTargetModel(event.target.value); }}><option value="">미지정(기본 모델)</option><option value="auto">auto(자동 선택)</option>{publicModels.map((model) => <option key={model.model_id} value={model.model_id}>{model.model_id}</option>)}</select><label htmlFor="test-reasoning">추론 등급</label><select id="test-reasoning" value={reasoningEffort} onChange={(event) => { setReasoningEffort(event.target.value); }}><option value="provider_default">미지정(기본값)</option><option value="low">low</option><option value="medium">medium</option><option value="high">high</option></select><label htmlFor="test-media">질문에 첨부할 이미지 또는 PDF · 최대 2 MiB</label><input ref={fileInput} id="test-media" type="file" accept="image/png,image/jpeg,image/webp,application/pdf" onChange={(event) => { setMedia(event.target.files?.[0] ?? null); }} required /><label htmlFor="test-request">질문</label><textarea id="test-request" value={request} onChange={(event) => { setRequest(event.target.value); }} required /><button type="submit">전체 파이프라인 시험</button></form></section><section aria-labelledby="external-test-title" className="result-panel"><h2 id="external-test-title">외부 클라이언트 → Media Bridge 전체 흐름 시험</h2><p>OpenAI SDK, OmniRoute 등 외부 클라이언트가 Media Bridge를 Provider로 호출하는 실제 API 흐름을 시험합니다.</p><form className="form-grid compact-form" onSubmit={(event) => { void submitExternal(event); }}><label htmlFor="external-model">공개 모델</label><select id="external-model" value={externalTargetModel} onChange={(event) => { setExternalTargetModel(event.target.value); }}><option value="">미지정(기본 모델)</option><option value="auto">auto(자동 선택)</option>{publicModels.map((model) => <option key={model.model_id} value={model.model_id}>{model.model_id}</option>)}</select><label htmlFor="external-reasoning">추론 등급</label><select id="external-reasoning" value={externalReasoningEffort} onChange={(event) => { setExternalReasoningEffort(event.target.value); }}><option value="provider_default">미지정(기본값)</option><option value="low">low</option><option value="medium">medium</option><option value="high">high</option></select><label htmlFor="external-endpoint">외부 클라이언트가 호출할 Media Bridge endpoint</label><input id="external-endpoint" type="url" value={externalEndpoint} onChange={(event) => { setExternalEndpoint(event.target.value); }} placeholder="https://media-bridge.example.com" required /><p>기본 주소만 입력하세요. <code>/v1</code>는 자동으로 붙습니다.</p><label htmlFor="external-api-key">Media Bridge 접근 키 원문</label><input id="external-api-key" type="password" value={externalApiKey} onChange={(event) => { setExternalApiKey(event.target.value); }} placeholder="mbc_..." required /><p>접근 키 관리에서 발급할 때 표시된 원문 키를 입력하세요.</p><button type="submit">외부 클라이언트 전체 흐름 시험</button></form></section>{error ? <p role="alert">시험 실패: {error}</p> : null}{result ? <section className="result-panel" aria-label="시험 결과"><div className="inline-actions"><strong>시험 결과 · {resultSource === "external" ? "외부 클라이언트 → Media Bridge" : "전체 파이프라인(Control)"}</strong><button className="secondary-button" type="button" onClick={clearResult}>결과 지우기</button></div><pre>{JSON.stringify(result, null, 2)}</pre></section> : null}</section>;
}
