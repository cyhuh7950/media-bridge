import { useState } from "react";

import { adminRequest } from "../api/client";

interface DraftResponse {
  draft_id: string;
}

export function PublishStep({ csrfToken, onPublished }: { csrfToken: string; onPublished: () => Promise<void> }) {
  const [failed, setFailed] = useState(false);

  async function publish() {
    setFailed(false);
    try {
      const draft = await adminRequest<DraftResponse>("/drafts/validate", {
        method: "POST",
        csrfToken,
        body: {},
      });
      if (typeof draft.draft_id !== "string") throw new Error("invalid response");
      await adminRequest("/snapshots", {
        method: "POST",
        csrfToken,
        body: { draft_id: draft.draft_id },
      });
      await onPublished();
    } catch {
      setFailed(true);
    }
  }

  return (
    <section className="setup-card" aria-labelledby="publish-step-title">
      <p className="step-label">7 · 검증과 발행</p>
      <h1 id="publish-step-title">설정 검증 및 발행</h1>
      <p>Provider·model capability·fail-closed policy를 검증한 뒤 서명 snapshot을 발행합니다.</p>
      {failed ? <p role="alert">설정을 발행할 수 없습니다. 입력과 capability 근거를 확인하세요.</p> : null}
      <button type="button" onClick={() => { void publish(); }}>검증하고 첫 snapshot 발행</button>
    </section>
  );
}
