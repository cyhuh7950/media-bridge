import { useState, type SyntheticEvent } from "react";

import { adminRequest, SafeApiError } from "../api/client";
import { ProviderCatalogPicker, type ProviderCatalogEntry, type ManagedProviderKind } from "../providers/ProviderCatalogPicker";

export function ProviderStep({ csrfToken, onSaved }: { csrfToken: string; onSaved: () => Promise<void> }) {
  const [name, setName] = useState("");
  const [kind, setKind] = useState<ManagedProviderKind>("analysis");
  const [catalogId, setCatalogId] = useState("");
  const [protocol, setProtocol] = useState("");
  const [capabilities, setCapabilities] = useState<string[]>([]);
  const [endpoint, setEndpoint] = useState("");
  const [apiKey, setApiKey] = useState("");
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
          kind,
          catalog_id: catalogId,
          endpoint,
          protocol,
          capabilities,
          secret_ref: { kind: "db", identifier: "provider_api_key" },
          api_key: apiKey || undefined,
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
      <h1 id="provider-step-title">Provider 연결 설정</h1>
      <p>Provider 연결은 선택 사항입니다. 지금 설정하거나 나중에 콘솔에서 등록할 수 있습니다.</p>
      <form className="form-grid" onSubmit={(event) => { void submit(event); }}>
        <label htmlFor="provider-kind">Provider 유형</label>
        <select id="provider-kind" value={kind} onChange={(event) => { setKind(event.target.value as ManagedProviderKind); setCatalogId(""); }}>
          <option value="analysis">분석 Provider</option>
          <option value="llm">Non-Vision LLM Provider</option>
        </select>
        <ProviderCatalogPicker kind={kind} value={catalogId} onChange={(entry: ProviderCatalogEntry | null) => {
          setCatalogId(entry?.provider_id ?? "");
          setName(entry?.display_name ?? "");
          setEndpoint(entry?.default_endpoint ?? "");
          setProtocol(entry?.protocol ?? "");
          setCapabilities(entry?.capabilities ?? []);
        }} />
        <label htmlFor="provider-name">Provider 이름</label>
        <input id="provider-name" value={name} onChange={(event) => { setName(event.target.value); }} required />
        <label htmlFor="provider-endpoint">HTTPS endpoint</label>
        <input id="provider-endpoint" type="url" value={endpoint} onChange={(event) => { setEndpoint(event.target.value); }} required />
        <label htmlFor="provider-api-key">Provider API 키</label>
        <input id="provider-api-key" type="password" value={apiKey} onChange={(event) => { setApiKey(event.target.value); }} autoComplete="new-password" required={Boolean(catalogId)} />
        {error ? <p role="alert">Provider를 저장할 수 없습니다.</p> : null}
        <button type="submit">Provider 저장</button>
      </form>
      <p><a href="/">지금은 건너뛰고 콘솔로 이동</a></p>
    </section>
  );
}
