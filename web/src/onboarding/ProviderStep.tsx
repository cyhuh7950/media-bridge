import { useState, type SyntheticEvent } from "react";

import { adminRequest, SafeApiError } from "../api/client";

export function ProviderStep({ csrfToken, onSaved }: { csrfToken: string; onSaved: () => Promise<void> }) {
  const [name, setName] = useState("");
  const [endpoint, setEndpoint] = useState("");
  const [reference, setReference] = useState("");
  const [error, setError] = useState(false);

  async function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(false);
    try {
      await adminRequest("/providers", {
        method: "POST",
        csrfToken,
        body: {
          name,
          kind: "vision",
          endpoint,
          secret_ref: { kind: "env", identifier: reference },
          enabled: true,
        },
      });
      await onSaved();
    } catch (caught: unknown) {
      setError(caught instanceof SafeApiError || caught instanceof Error);
    }
  }

  return (
    <section className="setup-card" aria-labelledby="provider-step-title">
      <p className="step-label">3 · Provider</p>
      <h1 id="provider-step-title">분석 Provider 등록</h1>
      <p>API Secret 원문이 아닌 환경변수 이름만 저장합니다.</p>
      <form className="form-grid" onSubmit={(event) => { void submit(event); }}>
        <label htmlFor="provider-name">Provider 이름</label>
        <input id="provider-name" value={name} onChange={(event) => { setName(event.target.value); }} required />
        <label htmlFor="provider-endpoint">HTTPS endpoint</label>
        <input id="provider-endpoint" type="url" value={endpoint} onChange={(event) => { setEndpoint(event.target.value); }} required />
        <label htmlFor="provider-reference">Secret 환경변수 이름</label>
        <input id="provider-reference" value={reference} onChange={(event) => { setReference(event.target.value); }} pattern="[A-Z][A-Z0-9_]*" required />
        {error ? <p role="alert">Provider를 저장할 수 없습니다.</p> : null}
        <button type="submit">Provider 저장</button>
      </form>
    </section>
  );
}
