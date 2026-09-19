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

export function TestLabPage({ role, csrfToken, resultTtlMs = RESULT_TTL_MS }: TestLabPageProps) {
  const [request, setRequest] = useState("");
  const [media, setMedia] = useState<File | null>(null);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const writable = role !== "viewer" && csrfToken !== null;

  useEffect(() => {
    if (result === null) return;
    const timer = window.setTimeout(() => { setResult(null); setRequest(""); setMedia(null); if (fileInput.current) fileInput.current.value = ""; }, resultTtlMs);
    return () => { window.clearTimeout(timer); };
  }, [result, resultTtlMs]);

  function clearResult() { setResult(null); setRequest(""); setMedia(null); if (fileInput.current) fileInput.current.value = ""; }

  async function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!writable || media === null || media.size < 1 || media.size > MAX_MEDIA_BYTES) { setError(true); return; }
    setError(false); setResult(null);
    try {
      const response = await adminRequest<unknown>("/test-lab/preview", { method: "POST", csrfToken, body: { target_model: "auto", conversion_profile: "generic", user_request: request, media_type: media.type === "application/pdf" ? "pdf" : "image", filename: media.name, declared_mime: media.type, media_base64: await toBase64(media) } });
      setResult(resultRecord(response));
    } catch { setError(true); }
  }

  if (!writable) return <section aria-labelledby="test-lab-title"><h1 id="test-lab-title">테스트 랩</h1><p>viewer는 시험을 실행할 수 없습니다.</p></section>;

  return <section aria-labelledby="test-lab-title"><h1 id="test-lab-title">테스트 랩</h1><p>선택한 파일과 질문으로 한 번의 테스트를 실행하고 결과를 확인합니다.</p><section aria-labelledby="deployment-endpoints-title" className="result-panel"><h2 id="deployment-endpoints-title">배포형 Media Bridge API endpoint</h2><p>기본 주소: <code>https://media-bridge.sinsan.kr</code></p><ul><li>OpenAI Responses API: <code>https://media-bridge.sinsan.kr/v1/responses</code></li><li>OpenAI Chat Completions: <code>https://media-bridge.sinsan.kr/v1/chat/completions</code></li><li>모델 조회: <code>https://media-bridge.sinsan.kr/v1/models</code></li><li>MCP: <code>https://media-bridge.sinsan.kr/mcp</code></li><li>Asset 업로드: <code>https://media-bridge.sinsan.kr/assets</code></li></ul></section><section aria-labelledby="full-test-title" className="result-panel"><h2 id="full-test-title">전체 파이프라인 시험</h2><p>파일과 질문을 입력하면 처리 결과를 아래에 표시합니다.</p><form className="form-grid compact-form" onSubmit={(event) => { void submit(event); }}><label htmlFor="test-media">질문에 첨부할 이미지 또는 PDF · 최대 2 MiB</label><input ref={fileInput} id="test-media" type="file" accept="image/png,image/jpeg,image/webp,application/pdf" onChange={(event) => { setMedia(event.target.files?.[0] ?? null); }} required /><label htmlFor="test-request">질문</label><textarea id="test-request" value={request} onChange={(event) => { setRequest(event.target.value); }} required /><button type="submit">전체 파이프라인 시험</button></form></section>{error ? <p role="alert">시험을 안전하게 완료하지 못했습니다.</p> : null}{result ? <section className="result-panel" aria-label="시험 결과"><div className="inline-actions"><strong>시험 결과</strong><button className="secondary-button" type="button" onClick={clearResult}>결과 지우기</button></div><pre>{JSON.stringify(result, null, 2)}</pre></section> : null}</section>;
}
