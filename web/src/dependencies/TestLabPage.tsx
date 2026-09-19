import { useEffect, useRef, useState, type SyntheticEvent } from "react";
import { adminRequest } from "../api/client";
import type { OperationsProps } from "../operations/operationTypes";

const RESULT_TTL_MS = 10 * 60 * 1000;
const MAX_MEDIA_BYTES = 2 * 1024 * 1024;

async function toBase64(file: File): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += 32768) binary += String.fromCharCode(...bytes.subarray(offset, offset + 32768));
  return btoa(binary);
}

function resultRecord(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null) throw new Error("invalid response");
  return value as Record<string, unknown>;
}

interface TestLabPageProps extends OperationsProps { resultTtlMs?: number; }
type RoutingProfile = { id: string; name: string; enabled: boolean };

export function TestLabPage({ role, csrfToken, resultTtlMs = RESULT_TTL_MS }: TestLabPageProps) {
  const [request, setRequest] = useState("");
  const [media, setMedia] = useState<File | null>(null);
  const [routingProfiles, setRoutingProfiles] = useState<RoutingProfile[]>([]);
  const [routingProfileId, setRoutingProfileId] = useState("");
  const [omniRouteEndpoint, setOmniRouteEndpoint] = useState("");
  const [omniRouteApiKey, setOmniRouteApiKey] = useState("");
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const writable = role !== "viewer" && csrfToken !== null;

  useEffect(() => {
    let active = true;
    void adminRequest<RoutingProfile[]>("/routing-profiles").then((profiles) => {
      if (!active) return;
      const enabled = profiles.filter((profile) => profile.enabled);
      setRoutingProfiles(enabled);
      setRoutingProfileId((current) => current || enabled[0]?.id || "");
    }).catch(() => { if (active) setRoutingProfiles([]); });
    return () => { active = false; };
  }, []);


  useEffect(() => {
    if (result === null) return;
    const timer = window.setTimeout(() => { setResult(null); setRequest(""); setMedia(null); if (fileInput.current) fileInput.current.value = ""; }, resultTtlMs);
    return () => { window.clearTimeout(timer); };
  }, [result, resultTtlMs]);

  function clearResult() { setResult(null); setRequest(""); setMedia(null); if (fileInput.current) fileInput.current.value = ""; }

  async function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!writable || !routingProfileId || media === null || media.size < 1 || media.size > MAX_MEDIA_BYTES) { setError("입력값을 확인하세요."); return; }
    setError(null); setResult(null);
    try {
      const response = await adminRequest<unknown>("/test-lab/preview", { method: "POST", csrfToken, body: { routing_profile_id: routingProfileId, target_model: "auto", conversion_profile: "generic", user_request: request, media_type: media.type === "application/pdf" ? "pdf" : "image", filename: media.name, declared_mime: media.type, media_base64: await toBase64(media) } });
      setResult(resultRecord(response));
    } catch (caught) { setError(caught instanceof Error ? caught.message : "upstream_or_downstream_failed"); }
  }

  async function submitOmniRoute(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!writable || !routingProfileId || media === null || !omniRouteEndpoint || !omniRouteApiKey || media.size < 1 || media.size > MAX_MEDIA_BYTES) {
      setError("라우팅, 파일, Media Bridge endpoint와 접근 키 원문을 확인하세요.");
      return;
    }
    setError(null); setResult(null);
    try {
      const response = await adminRequest<unknown>("/test-lab/run", { method: "POST", csrfToken, body: {
        routing_profile_id: routingProfileId,
        gateway_url: omniRouteEndpoint,
        api_key: omniRouteApiKey,
        target_model: "auto",
        conversion_profile: "generic",
        user_request: request,
        media_type: media.type === "application/pdf" ? "pdf" : "image",
        filename: media.name,
        declared_mime: media.type,
        media_base64: await toBase64(media),
        execute_downstream: true,
      } });
      setResult(resultRecord(response));
    } catch (caught) { setError(caught instanceof Error ? caught.message : "omniroute_media_bridge_failed"); }
  }

  if (!writable) return <section aria-labelledby="test-lab-title"><h1 id="test-lab-title">테스트 랩</h1><p>viewer는 시험을 실행할 수 없습니다.</p></section>;

  return <section aria-labelledby="test-lab-title"><h1 id="test-lab-title">테스트 랩</h1><p>선택한 라우팅으로 upstream부터 downstream까지 실행하고 결과를 확인합니다.</p><section aria-labelledby="deployment-endpoints-title" className="result-panel"><h2 id="deployment-endpoints-title">배포형 Media Bridge API endpoint</h2><p>기본 주소: <code>https://media-bridge.sinsan.kr</code></p><ul><li>OpenAI Responses API: <code>https://media-bridge.sinsan.kr/v1/responses</code></li><li>OpenAI Chat Completions: <code>https://media-bridge.sinsan.kr/v1/chat/completions</code></li><li>모델 조회: <code>https://media-bridge.sinsan.kr/v1/models</code></li><li>MCP: <code>https://media-bridge.sinsan.kr/mcp</code></li><li>Asset 업로드: <code>https://media-bridge.sinsan.kr/assets</code></li></ul></section><section aria-labelledby="full-test-title" className="result-panel"><h2 id="full-test-title">전체 파이프라인 시험</h2><p>라우팅을 선택하고 파일과 질문을 입력하면 upstream과 downstream 결과를 아래에 표시합니다.</p><form className="form-grid compact-form" onSubmit={(event) => { void submit(event); }}><label htmlFor="routing-profile">라우팅 프로필</label><select id="routing-profile" value={routingProfileId} onChange={(event) => { setRoutingProfileId(event.target.value); }} required><option value="">선택</option>{routingProfiles.map((profile) => <option key={profile.id} value={profile.id}>{profile.name}</option>)}</select><label htmlFor="test-media">질문에 첨부할 이미지 또는 PDF · 최대 2 MiB</label><input ref={fileInput} id="test-media" type="file" accept="image/png,image/jpeg,image/webp,application/pdf" onChange={(event) => { setMedia(event.target.files?.[0] ?? null); }} required /><label htmlFor="test-request">질문</label><textarea id="test-request" value={request} onChange={(event) => { setRequest(event.target.value); }} required /><button type="submit">전체 파이프라인 시험</button></form></section><section aria-labelledby="omniroute-test-title" className="result-panel"><h2 id="omniroute-test-title">OmniRoute → Media Bridge 전체 흐름 시험</h2><p>위에서 선택한 라우팅과 같은 파일·질문으로 OmniRoute에서 Media Bridge를 거쳐 upstage-document-parse와 Solar 4까지 실제 API 경로를 호출합니다.</p><form className="form-grid compact-form" onSubmit={(event) => { void submitOmniRoute(event); }}><label htmlFor="omniroute-endpoint">OmniRoute가 호출할 Media Bridge endpoint</label><input id="omniroute-endpoint" type="url" value={omniRouteEndpoint} onChange={(event) => { setOmniRouteEndpoint(event.target.value); }} placeholder="https://media-bridge.sinsan.kr" required /><p>기본 주소만 입력하세요. <code>/v1</code>는 자동으로 붙습니다.</p><label htmlFor="omniroute-api-key">Media Bridge 접근 키 원문</label><input id="omniroute-api-key" type="password" value={omniRouteApiKey} onChange={(event) => { setOmniRouteApiKey(event.target.value); }} placeholder="mbc_..." required /><p>접근 키 관리에서 발급할 때 표시된 원문 키를 입력하세요. 관리 목록의 이름만으로는 원문 키를 복구할 수 없습니다.</p><button type="submit">OmniRoute 전체 흐름 시험</button></form></section>{error ? <p role="alert">시험 실패: {error}</p> : null}{result ? <section className="result-panel" aria-label="시험 결과"><div className="inline-actions"><strong>시험 결과</strong><button className="secondary-button" type="button" onClick={clearResult}>결과 지우기</button></div><pre>{JSON.stringify(result, null, 2)}</pre></section> : null}</section>;
}
