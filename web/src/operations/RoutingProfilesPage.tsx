import { useEffect, useState, type SyntheticEvent } from "react";

import { adminRequest } from "../api/client";
import type { OperationsProps } from "./operationTypes";

type Provider = { id: string; name: string; kind: string };
type Profile = {
  id: string;
  name: string;
  analysis_provider_ids: string[];
  llm_provider_ids: string[];
  strategy: string;
  enabled: boolean;
};

export function RoutingProfilesPage({ role, csrfToken }: OperationsProps) {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [name, setName] = useState("");
  const [analysisIds, setAnalysisIds] = useState<string[]>([]);
  const [llmIds, setLlmIds] = useState<string[]>([]);
  const [strategy, setStrategy] = useState("priority");
  const [failed, setFailed] = useState(false);
  const writable = role !== "viewer" && csrfToken !== null;

  async function reload() {
    try {
      const [providerPayload, profilePayload] = await Promise.all([
        adminRequest<Provider[]>("/providers"),
        adminRequest<Profile[]>("/routing-profiles"),
      ]);
      setProviders(providerPayload);
      setProfiles(profilePayload);
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }

  useEffect(() => {
    let active = true;
    void Promise.all([
      adminRequest<Provider[]>("/providers"),
      adminRequest<Profile[]>("/routing-profiles"),
    ]).then(([providerPayload, profilePayload]) => {
      if (!active) return;
      setProviders(providerPayload);
      setProfiles(profilePayload);
      setFailed(false);
    }).catch(() => {
      if (active) setFailed(true);
    });
    return () => { active = false; };
  }, []);

  async function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!writable) return;
    try {
      await adminRequest("/routing-profiles", {
        method: "POST",
        csrfToken,
        body: {
          name,
          analysis_provider_ids: analysisIds,
          llm_provider_ids: llmIds,
          strategy,
          enabled: true,
        },
      });
      setName("");
      setAnalysisIds([]);
      setLlmIds([]);
      await reload();
    } catch {
      setFailed(true);
    }
  }

  const analysis = providers.filter((provider) => ["analysis", "vision", "ocr"].includes(provider.kind));
  const llm = providers.filter((provider) => provider.kind === "llm");
  return (
    <section aria-labelledby="routing-profiles-title">
      <h1 id="routing-profiles-title">라우팅 프로필</h1>
      <p>분석 Provider와 Non‑Vision LLM Provider를 N:N으로 연결하고 선택 정책을 관리합니다.</p>
      {failed ? <p role="alert">Routing profile을 불러오거나 저장할 수 없습니다.</p> : null}
      <table><thead><tr><th>이름</th><th>분석 Provider</th><th>LLM Provider</th><th>전략</th></tr></thead>
        <tbody>{profiles.map((profile) => <tr key={profile.id}><td>{profile.name}</td><td>{profile.analysis_provider_ids.length}</td><td>{profile.llm_provider_ids.length}</td><td>{profile.strategy}</td></tr>)}</tbody>
      </table>
      {writable ? <form className="form-grid compact-form" onSubmit={(event) => { void submit(event); }}>
        <h2>Routing profile 추가</h2>
        <label htmlFor="routing-profile-name">이름</label>
        <input id="routing-profile-name" value={name} onChange={(event) => { setName(event.target.value); }} required />
        <label htmlFor="routing-profile-analysis">분석 Provider</label>
        <select id="routing-profile-analysis" multiple value={analysisIds} onChange={(event) => { setAnalysisIds(Array.from(event.target.selectedOptions, (option) => option.value)); }} required>
          {analysis.map((provider) => <option key={provider.id} value={provider.id}>{provider.name}</option>)}
        </select>
        <label htmlFor="routing-profile-llm">Non-Vision LLM Provider</label>
        <select id="routing-profile-llm" multiple value={llmIds} onChange={(event) => { setLlmIds(Array.from(event.target.selectedOptions, (option) => option.value)); }} required>
          {llm.map((provider) => <option key={provider.id} value={provider.id}>{provider.name}</option>)}
        </select>
        <label htmlFor="routing-profile-strategy">선택 전략</label>
        <select id="routing-profile-strategy" value={strategy} onChange={(event) => { setStrategy(event.target.value); }}>
          <option value="priority">우선순위</option><option value="fallback">Fallback</option><option value="health">상태 우선</option><option value="cost">비용 우선</option>
        </select>
        <button type="submit">Routing profile 저장</button>
      </form> : <p>viewer는 Routing profile 설정을 읽기만 할 수 있습니다.</p>}
    </section>
  );
}
