import { useEffect, useRef, useState, type SyntheticEvent } from "react";

import { adminRequest } from "../api/client";
import type { OperationsProps } from "../operations/operationTypes";
import { textField } from "../operations/operationTypes";
import { useAdminList } from "../operations/useAdminList";

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

interface TestLabPageProps extends OperationsProps {
  resultTtlMs?: number;
}

export function TestLabPage({ role, csrfToken, resultTtlMs = RESULT_TTL_MS }: TestLabPageProps) {
  const { items: connections, failed } = useAdminList(
    role === "viewer" ? null : "/connections",
  );
  const [connectionId, setConnectionId] = useState("");
  const [targetModel, setTargetModel] = useState("");
  const [profile, setProfile] = useState("generic");
  const [userRequest, setUserRequest] = useState("");
  const [media, setMedia] = useState<File | null>(null);
  const [executeDownstream, setExecuteDownstream] = useState(false);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const writable = role !== "viewer" && csrfToken !== null;

  useEffect(() => {
    if (result === null) return;
    const timer = window.setTimeout(() => {
      setResult(null);
      setUserRequest("");
      setMedia(null);
      setExecuteDownstream(false);
      if (fileInput.current) fileInput.current.value = "";
    }, resultTtlMs);
    return () => { window.clearTimeout(timer); };
  }, [result, resultTtlMs]);

  function clearTransient() {
    setResult(null);
    setUserRequest("");
    setMedia(null);
    setExecuteDownstream(false);
    if (fileInput.current) fileInput.current.value = "";
  }

  async function submit(event: SyntheticEvent, run: boolean) {
    event.preventDefault();
    if (!writable || media === null || (run && !executeDownstream)) return;
    if (media.size < 1 || media.size > MAX_MEDIA_BYTES) {
      setError(true);
      clearTransient();
      return;
    }
    const currentMedia = media;
    const currentRequest = userRequest;
    setResult(null);
    setError(false);
    setMedia(null);
    setUserRequest("");
    setExecuteDownstream(false);
    if (fileInput.current) fileInput.current.value = "";
    try {
      const mediaBase64 = await toBase64(currentMedia);
      const mediaType = currentMedia.type === "application/pdf" ? "pdf" : "image";
      const response = await adminRequest<unknown>(run ? "/test-lab/run" : "/test-lab/preview", {
        method: "POST",
        csrfToken,
        body: {
          connection_id: connectionId,
          target_model: targetModel,
          conversion_profile: profile,
          user_request: currentRequest,
          media_type: mediaType,
          filename: currentMedia.name,
          declared_mime: currentMedia.type,
          media_base64: mediaBase64,
          ...(run ? { execute_downstream: true } : {}),
        },
      });
      setResult(resultRecord(response));
    } catch {
      setError(true);
    }
  }

  if (!writable) {
    return <section aria-labelledby="test-lab-title"><h1 id="test-lab-title">Test Lab</h1><p>viewer는 시험 본문을 만들거나 downstream을 호출할 수 없습니다.</p></section>;
  }

  return (
    <section aria-labelledby="test-lab-title">
      <h1 id="test-lab-title">Test Lab</h1>
      <p>Preview는 provider를 호출하지 않습니다. 실제 downstream 시험은 매번 명시적으로 허용해야 합니다.</p>
      {failed ? <p role="alert">Connection 목록을 불러올 수 없습니다.</p> : null}
      <form className="form-grid compact-form" onSubmit={(event) => { void submit(event, false); }}>
        <label htmlFor="test-lab-connection">Connection</label>
        <select id="test-lab-connection" value={connectionId} onChange={(event) => { setConnectionId(event.target.value); }} required>
          <option value="">선택</option>
          {(connections ?? []).filter((item) => textField(item, "status") !== "revoked").map((item) => <option key={textField(item, "id")} value={textField(item, "id")}>{textField(item, "name")}</option>)}
        </select>
        <label htmlFor="test-lab-model">대상 모델</label>
        <input id="test-lab-model" value={targetModel} onChange={(event) => { setTargetModel(event.target.value); }} pattern="[a-z0-9][a-z0-9./:_-]*" required />
        <label htmlFor="test-lab-profile">변환 profile</label>
        <select id="test-lab-profile" value={profile} onChange={(event) => { setProfile(event.target.value); }}>
          <option value="generic">generic</option><option value="error_screenshot">error_screenshot</option><option value="document">document</option>
        </select>
        <label htmlFor="test-lab-request">사용자 요청</label>
        <textarea id="test-lab-request" value={userRequest} onChange={(event) => { setUserRequest(event.target.value); }} required />
        <label htmlFor="test-lab-media">이미지 또는 PDF · 최대 2 MiB</label>
        <input ref={fileInput} id="test-lab-media" type="file" accept="image/png,image/jpeg,image/webp,application/pdf" onChange={(event) => { setMedia(event.target.files?.[0] ?? null); }} required />
        <div className="inline-actions"><button type="submit">Preview</button></div>
        <label className="checkbox-row" htmlFor="test-lab-downstream"><input id="test-lab-downstream" type="checkbox" checked={executeDownstream} onChange={(event) => { setExecuteDownstream(event.target.checked); }} /><span>실제 downstream Provider 호출과 비용 발생을 이번 1회에 한해 허용합니다.</span></label>
        <button type="button" disabled={!executeDownstream} onClick={(event) => { void submit(event, true); }}>실제 downstream 시험</button>
      </form>
      {error ? <p role="alert">시험을 안전하게 완료하지 못했습니다.</p> : null}
      {result ? <section className="result-panel" aria-label="시험 결과"><div className="inline-actions"><strong>일시 결과</strong><button className="secondary-button" type="button" onClick={clearTransient}>결과 지우기</button></div><pre>{JSON.stringify(result, null, 2)}</pre></section> : null}
    </section>
  );
}
