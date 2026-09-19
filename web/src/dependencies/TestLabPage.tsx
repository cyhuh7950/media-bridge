import { useEffect, useRef, useState, type SyntheticEvent } from "react";

import { adminRequest } from "../api/client";
import type { OperationsProps } from "../operations/operationTypes";

const RESULT_TTL_MS = 10 * 60 * 1000;
const MAX_MEDIA_BYTES = 2 * 1024 * 1024;

async function toBase64(file: File): Promise<string> {
  const buffer = await new Promise<ArrayBuffer>((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => { reject(new Error("media_read_failed")); };
    reader.onload = () => {
      if (reader.result instanceof ArrayBuffer) resolve(reader.result);
      else reject(new Error("media_read_failed"));
    };
    reader.readAsArrayBuffer(file);
  });
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += 32768) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 32768));
  }
  return btoa(binary);
}

function resultRecord(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null) throw new Error("invalid response");
  return value as Record<string, unknown>;
}

interface TestLabPageProps extends OperationsProps { resultTtlMs?: number; }

export function TestLabPage({ role, csrfToken, resultTtlMs = RESULT_TTL_MS }: TestLabPageProps) {
  const [previewModel, setPreviewModel] = useState("");
  const [previewProfile, setPreviewProfile] = useState("generic");
  const [previewRequest, setPreviewRequest] = useState("");
  const [previewMedia, setPreviewMedia] = useState<File | null>(null);
  const [downstreamUrl, setDownstreamUrl] = useState("");
  const [downstreamKey, setDownstreamKey] = useState("");
  const [downstreamModel, setDownstreamModel] = useState("");
  const [downstreamProfile, setDownstreamProfile] = useState("generic");
  const [downstreamRequest, setDownstreamRequest] = useState("");
  const [downstreamMedia, setDownstreamMedia] = useState<File | null>(null);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState(false);
  const previewFileInput = useRef<HTMLInputElement>(null);
  const downstreamFileInput = useRef<HTMLInputElement>(null);
  const writable = role !== "viewer" && csrfToken !== null;

  useEffect(() => {
    if (result === null) return;
    const timer = window.setTimeout(() => {
      setResult(null); setPreviewRequest(""); setPreviewMedia(null);
      setDownstreamRequest(""); setDownstreamMedia(null);
      if (previewFileInput.current) previewFileInput.current.value = "";
      if (downstreamFileInput.current) downstreamFileInput.current.value = "";
    }, resultTtlMs);
    return () => { window.clearTimeout(timer); };
  }, [result, resultTtlMs]);

  function clearTransient() {
    setResult(null); setPreviewRequest(""); setPreviewMedia(null);
    setDownstreamRequest(""); setDownstreamMedia(null);
    if (previewFileInput.current) previewFileInput.current.value = "";
    if (downstreamFileInput.current) downstreamFileInput.current.value = "";
  }

  async function submit(event: SyntheticEvent, run: boolean) {
    event.preventDefault();
    const media = run ? downstreamMedia : previewMedia;
    const userRequest = run ? downstreamRequest : previewRequest;
    const targetModel = run ? downstreamModel : previewModel;
    const profile = run ? downstreamProfile : previewProfile;
    if (!writable || media === null || (run && (!downstreamUrl || !downstreamKey))) return;
    if (media.size < 1 || media.size > MAX_MEDIA_BYTES) { setError(true); clearTransient(); return; }
    setResult(null); setError(false);
    try {
      const mediaBase64 = await toBase64(media);
      const mediaType = media.type === "application/pdf" ? "pdf" : "image";
      const response = await adminRequest<unknown>(run ? "/test-lab/run" : "/test-lab/preview", {
        method: "POST", csrfToken,
        body: {
          ...(run ? { gateway_url: downstreamUrl, api_key: downstreamKey, execute_downstream: true } : {}),
          target_model: targetModel, conversion_profile: profile, user_request: userRequest,
          media_type: mediaType, filename: media.name, declared_mime: media.type, media_base64: mediaBase64,
        },
      });
      setResult(resultRecord(response));
    } catch { setError(true); }
  }

  if (!writable) return <section aria-labelledby="test-lab-title"><h1 id="test-lab-title">테스트 랩</h1><p>viewer는 시험 본문을 만들거나 downstream을 호출할 수 없습니다.</p></section>;

  return <section aria-labelledby="test-lab-title">
    <h1 id="test-lab-title">테스트 랩</h1>
    <p>Preview와 실제 downstream 테스트는 입력과 실행을 분리합니다.</p>
    <section aria-labelledby="deployment-endpoints-title" className="result-panel">
      <h2 id="deployment-endpoints-title">배포형 Media Bridge API endpoint</h2>
      <p>기본 주소: <code>https://media-bridge.sinsan.kr</code></p>
      <ul>
        <li>OpenAI Responses API: <code>https://media-bridge.sinsan.kr/v1/responses</code></li>
        <li>OpenAI Chat Completions: <code>https://media-bridge.sinsan.kr/v1/chat/completions</code></li>
        <li>모델 조회: <code>https://media-bridge.sinsan.kr/v1/models</code></li>
        <li>MCP: <code>https://media-bridge.sinsan.kr/mcp</code></li>
        <li>Asset 업로드: <code>https://media-bridge.sinsan.kr/assets</code></li>
      </ul>
      <p>Provider 등록용 기본 endpoint: <code>https://media-bridge.sinsan.kr/v1</code></p>
    </section>
    <section aria-labelledby="preview-test-title" className="result-panel">
      <h2 id="preview-test-title">Preview 테스트</h2>
      <p>Provider나 downstream을 호출하지 않고 입력과 변환 결과만 확인합니다.</p>
      <form className="form-grid compact-form" onSubmit={(event) => { void submit(event, false); }}>
        <label htmlFor="preview-model">Preview 테스트 대상 모델</label><input id="preview-model" value={previewModel} onChange={(event) => { setPreviewModel(event.target.value); }} pattern="[a-z0-9][a-z0-9./:_-]*" required />
        <label htmlFor="preview-profile">변환 profile</label><select id="preview-profile" value={previewProfile} onChange={(event) => { setPreviewProfile(event.target.value); }}><option value="generic">generic</option><option value="error_screenshot">error_screenshot</option><option value="document">document</option></select>
        <label htmlFor="preview-request">Preview 사용자 요청</label><textarea id="preview-request" value={previewRequest} onChange={(event) => { setPreviewRequest(event.target.value); }} required />
        <label htmlFor="preview-media">Preview 이미지 또는 PDF · 최대 2 MiB</label><input ref={previewFileInput} id="preview-media" type="file" accept="image/png,image/jpeg,image/webp,application/pdf" onChange={(event) => { setPreviewMedia(event.target.files?.[0] ?? null); }} required />
        <button type="submit">Preview 실행</button>
      </form>
    </section>
    <section aria-labelledby="downstream-test-title" className="result-panel">
      <h2 id="downstream-test-title">실제 downstream 테스트</h2>
      <p>입력한 endpoint로 실제 호출합니다. 호출할 때마다 API 키를 직접 입력합니다.</p>
      <form className="form-grid compact-form" onSubmit={(event) => { void submit(event, true); }}>
        <label htmlFor="downstream-endpoint">downstream API endpoint</label><input id="downstream-endpoint" type="url" value={downstreamUrl} onChange={(event) => { setDownstreamUrl(event.target.value); }} placeholder="https://gateway.example/v1" pattern="https://.*" required />
        <label htmlFor="downstream-api-key">downstream API 키</label><input id="downstream-api-key" type="password" value={downstreamKey} onChange={(event) => { setDownstreamKey(event.target.value); }} autoComplete="off" required />
        <label htmlFor="downstream-model">downstream 대상 모델</label><input id="downstream-model" value={downstreamModel} onChange={(event) => { setDownstreamModel(event.target.value); }} pattern="[a-z0-9][a-z0-9./:_-]*" required />
        <label htmlFor="downstream-profile">변환 profile</label><select id="downstream-profile" value={downstreamProfile} onChange={(event) => { setDownstreamProfile(event.target.value); }}><option value="generic">generic</option><option value="error_screenshot">error_screenshot</option><option value="document">document</option></select>
        <label htmlFor="downstream-request">downstream 사용자 요청</label><textarea id="downstream-request" value={downstreamRequest} onChange={(event) => { setDownstreamRequest(event.target.value); }} required />
        <label htmlFor="downstream-media">downstream 이미지 또는 PDF · 최대 2 MiB</label><input ref={downstreamFileInput} id="downstream-media" type="file" accept="image/png,image/jpeg,image/webp,application/pdf" onChange={(event) => { setDownstreamMedia(event.target.files?.[0] ?? null); }} required />
        <button type="submit">downstream 테스트 실행</button>
      </form>
    </section>
    {error ? <p role="alert">시험을 안전하게 완료하지 못했습니다.</p> : null}
    {result ? <section className="result-panel" aria-label="시험 결과"><div className="inline-actions"><strong>일시 결과</strong><button className="secondary-button" type="button" onClick={clearTransient}>결과 지우기</button></div><pre>{JSON.stringify(result, null, 2)}</pre></section> : null}
  </section>;
}
