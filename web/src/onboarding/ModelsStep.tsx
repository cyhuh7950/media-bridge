import { useState, type SyntheticEvent } from "react";

import { adminRequest } from "../api/client";

export function ModelsStep({ csrfToken, onSaved }: { csrfToken: string; onSaved: () => Promise<void> }) {
  const [modelId, setModelId] = useState("");
  const [evidence, setEvidence] = useState("");
  const [failed, setFailed] = useState(false);

  async function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    const reviewedAt = new Date();
    const expiresAt = new Date(reviewedAt.getTime() + 30 * 24 * 60 * 60 * 1000);
    try {
      await adminRequest("/models", {
        method: "POST",
        csrfToken,
        body: {
          model_id: modelId,
          aliases: [],
          input_modalities: ["text"],
          evidence,
          reviewed_at: reviewedAt.toISOString(),
          expires_at: expiresAt.toISOString(),
          pdf_passthrough_verified: false,
        },
      });
      await onSaved();
    } catch {
      setFailed(true);
    }
  }

  return (
    <section className="setup-card" aria-labelledby="model-step-title">
      <p className="step-label">4 · Model</p>
      <h1 id="model-step-title">대상 모델 등록</h1>
      <p>확인되지 않은 capability는 등록하지 말고 fail-closed 상태를 유지하세요.</p>
      <form className="form-grid" onSubmit={(event) => { void submit(event); }}>
        <label htmlFor="model-id">정확한 model ID</label>
        <input id="model-id" value={modelId} onChange={(event) => { setModelId(event.target.value); }} required />
        <label htmlFor="model-evidence">Capability 근거</label>
        <textarea id="model-evidence" value={evidence} onChange={(event) => { setEvidence(event.target.value); }} required />
        {failed ? <p role="alert">모델을 저장할 수 없습니다.</p> : null}
        <button type="submit">Non-Vision 모델 저장</button>
      </form>
    </section>
  );
}
