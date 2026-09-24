import { useEffect, useState } from "react";

import { adminRequest, SafeApiError } from "../api/client";

export type ManagedProviderKind = "analysis" | "llm";

export interface ProviderCatalogEntry {
  provider_id: string;
  display_name: string;
  kind: ManagedProviderKind;
  protocol: string;
  capabilities: string[];
  default_endpoint: string | null;
  secret_env: string | null;
  default_model_id: string;
}

export function ProviderCatalogPicker({
  kind,
  value,
  onChange,
}: {
  kind: ManagedProviderKind;
  value: string;
  onChange: (entry: ProviderCatalogEntry | null) => void;
}) {
  const [entries, setEntries] = useState<ProviderCatalogEntry[] | null>(null);
  const [loadedKind, setLoadedKind] = useState<ManagedProviderKind | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    void adminRequest<ProviderCatalogEntry[]>(`/provider-catalog?kind=${kind}`)
      .then((payload) => {
        if (active) {
          setEntries(payload);
          setLoadedKind(kind);
        }
      })
      .catch((error: unknown) => {
        if (active && (error instanceof SafeApiError || error instanceof Error)) setFailed(true);
      });
    return () => { active = false; };
  }, [kind]);

  return (
    <>
      <label htmlFor="provider-catalog">Provider 선택</label>
      <select
        id="provider-catalog"
        value={value}
        onChange={(event) => {
          const entry = entries?.find((item) => item.provider_id === event.target.value) ?? null;
          onChange(entry);
        }}
        required
        disabled={loadedKind !== kind}
      >
        <option value="">{loadedKind !== kind ? "목록을 불러오는 중…" : "Provider를 선택하세요"}</option>
        {loadedKind === kind ? <option value="__custom__">사용자 정의</option> : null}
        {loadedKind === kind ? entries?.map((entry) => <option key={entry.provider_id} value={entry.provider_id}>{entry.display_name}</option>) : null}
      </select>
      {failed ? <p role="alert">Provider 카탈로그를 불러올 수 없습니다.</p> : null}
    </>
  );
}
