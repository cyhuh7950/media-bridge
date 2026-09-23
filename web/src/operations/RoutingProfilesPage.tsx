import { useEffect, useState, type SyntheticEvent } from "react";

import { adminRequest } from "../api/client";
import type { OperationsProps } from "./operationTypes";

type Provider = { id: string; name: string; kind: string };
type Profile = { id: string; name: string; analysis_provider_ids: string[]; llm_provider_ids: string[]; strategy: string; enabled: boolean };
type DialogMode = "create" | "edit";

const strategyLabels: Record<string, string> = { priority: "우선순위", fallback: "대체 경로", health: "상태 우선", cost: "비용 우선" };
function providerNames(ids: string[], providers: Provider[]): string {
  const names = ids.map((id) => providers.find((provider) => provider.id === id)?.name ?? id);
  return names.length > 0 ? names.join(", ") : "없음";
}

export function RoutingProfilesPage({ role, csrfToken }: OperationsProps) {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [dialogMode, setDialogMode] = useState<DialogMode | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [name, setName] = useState("");
  const [analysisIds, setAnalysisIds] = useState<string[]>([]);
  const [llmIds, setLlmIds] = useState<string[]>([]);
  const [strategy, setStrategy] = useState("priority");
  const [failed, setFailed] = useState(false);
  const [saveFailed, setSaveFailed] = useState(false);
  const [deleteFailed, setDeleteFailed] = useState(false);
  const writable = role !== "viewer" && csrfToken !== null;
  const allSelected = profiles.length > 0 && selectedIds.length === profiles.length;

  async function reload() {
    try {
      const [providerPayload, profilePayload] = await Promise.all([adminRequest<Provider[]>("/providers"), adminRequest<Profile[]>("/routing-profiles")]);
      setProviders(providerPayload); setProfiles(profilePayload); setFailed(false);
    } catch { setFailed(true); }
  }
  useEffect(() => {
    let active = true;
    void Promise.all([adminRequest<Provider[]>("/providers"), adminRequest<Profile[]>("/routing-profiles")]).then(([providerPayload, profilePayload]) => {
      if (!active) return; setProviders(providerPayload); setProfiles(profilePayload); setFailed(false);
    }).catch(() => { if (active) setFailed(true); });
    return () => { active = false; };
  }, []);
  function closeDialog() { setDialogMode(null); setEditingId(null); setSaveFailed(false); }
  function openCreate() { setDialogMode("create"); setEditingId(null); setName(""); setAnalysisIds([]); setLlmIds([]); setStrategy("priority"); setSaveFailed(false); }
  function openEdit(profile: Profile) { setDialogMode("edit"); setEditingId(profile.id); setName(profile.name); setAnalysisIds(profile.analysis_provider_ids); setLlmIds(profile.llm_provider_ids); setStrategy(profile.strategy); setSaveFailed(false); }
  async function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault(); if (!writable || !dialogMode) return; setSaveFailed(false);
    try {
      const body = { name, analysis_provider_ids: analysisIds, llm_provider_ids: llmIds, strategy, enabled: true };
      if (dialogMode === "edit" && editingId) await adminRequest(`/routing-profiles/${editingId}`, { method: "PATCH", csrfToken, body });
      else await adminRequest("/routing-profiles", { method: "POST", csrfToken, body });
      closeDialog(); await reload();
    } catch { setSaveFailed(true); }
  }
  function toggleSelected(id: string, checked: boolean) { setSelectedIds((current) => checked ? [...new Set([...current, id])] : current.filter((value) => value !== id)); }
  async function deleteSelected() {
    if (!writable || selectedIds.length === 0 || !window.confirm("선택한 라우팅 프로필을 삭제하시겠습니까?")) return;
    setDeleteFailed(false);
    try { await Promise.all(selectedIds.map((id) => adminRequest(`/routing-profiles/${id}`, { method: "DELETE", csrfToken }))); setSelectedIds([]); await reload(); }
    catch { setDeleteFailed(true); }
  }
  const analysis = providers.filter((provider) => ["analysis", "vision", "ocr"].includes(provider.kind));
  const llm = providers.filter((provider) => provider.kind === "llm");
  return <section aria-labelledby="routing-profiles-title">
    <div className="page-heading"><div><h1 id="routing-profiles-title">내부 실행 라우팅 관리</h1><p>분석 Provider와 Non‑Vision LLM Provider를 N:N으로 연결하는 Media Bridge 내부 실행 정책입니다. 외부 model 값은 모델 관리에서 생성합니다.</p></div>{writable ? <button type="button" onClick={openCreate}>내부 라우팅 등록</button> : null}</div>
    {failed ? <p role="alert">라우팅 프로필 목록을 불러올 수 없습니다.</p> : null}{deleteFailed ? <p role="alert">선택한 라우팅 프로필을 모두 삭제하지 못했습니다.</p> : null}{!writable ? <p>viewer는 라우팅 프로필을 읽기만 할 수 있습니다.</p> : null}
    {profiles.length === 0 && !failed ? <p role="status">등록된 라우팅 프로필이 없습니다.</p> : null}
    {profiles.length > 0 ? <>{writable && selectedIds.length > 0 ? <div className="inline-actions"><button type="button" className="danger-button" onClick={() => { void deleteSelected(); }}>선택 삭제 ({selectedIds.length})</button></div> : null}
      <table><thead><tr>{writable ? <th><input aria-label="전체 라우팅 프로필 선택" type="checkbox" checked={allSelected} onChange={(event) => { setSelectedIds(event.target.checked ? profiles.map((profile) => profile.id) : []); }} /></th> : null}<th>이름</th><th>분석 Provider</th><th>Non‑Vision LLM Provider</th><th>전략</th><th>상태</th>{writable ? <th>작업</th> : null}</tr></thead>
        <tbody>{profiles.map((profile) => <tr key={profile.id}>{writable ? <td><input aria-label={`${profile.name} 선택`} type="checkbox" checked={selectedIds.includes(profile.id)} onChange={(event) => { toggleSelected(profile.id, event.target.checked); }} /></td> : null}<td>{profile.name}</td><td>{providerNames(profile.analysis_provider_ids, analysis)}</td><td>{providerNames(profile.llm_provider_ids, llm)}</td><td>{strategyLabels[profile.strategy] ?? profile.strategy}</td><td>{profile.enabled ? "활성" : "비활성"}</td>{writable ? <td><button type="button" className="secondary-button" onClick={() => { openEdit(profile); }}>수정</button></td> : null}</tr>)}</tbody>
      </table></> : null}
    {dialogMode ? <section className="dialog-backdrop" role="dialog" aria-modal="true" aria-labelledby="routing-profile-dialog-title"><form className="dialog-card form-grid" onSubmit={(event) => { void submit(event); }}><h2 id="routing-profile-dialog-title">{dialogMode === "create" ? "라우팅 프로필 등록" : "라우팅 프로필 수정"}</h2><p>여러 Provider를 선택하면 시스템이 전략에 따라 자동으로 선택합니다.</p>
      <label htmlFor="routing-profile-name">이름</label><input id="routing-profile-name" value={name} onChange={(event) => { setName(event.target.value); }} required />
      <label htmlFor="routing-profile-analysis">분석 Provider (복수 선택)</label><select id="routing-profile-analysis" multiple size={Math.min(6, Math.max(3, analysis.length))} value={analysisIds} onChange={(event) => { setAnalysisIds(Array.from(event.target.selectedOptions, (option) => option.value)); }} required>{analysis.map((provider) => <option key={provider.id} value={provider.id}>{provider.name}</option>)}</select>
      <label htmlFor="routing-profile-llm">Non‑Vision LLM Provider (복수 선택)</label><select id="routing-profile-llm" multiple size={Math.min(6, Math.max(3, llm.length))} value={llmIds} onChange={(event) => { setLlmIds(Array.from(event.target.selectedOptions, (option) => option.value)); }} required>{llm.map((provider) => <option key={provider.id} value={provider.id}>{provider.name}</option>)}</select>
      <label htmlFor="routing-profile-strategy">선택 전략</label><select id="routing-profile-strategy" value={strategy} onChange={(event) => { setStrategy(event.target.value); }}><option value="priority">우선순위</option><option value="fallback">대체 경로</option><option value="health">상태 우선</option><option value="cost">비용 우선</option></select>
      {saveFailed ? <p role="alert">라우팅 프로필을 저장할 수 없습니다.</p> : null}<div className="inline-actions"><button type="submit">{dialogMode === "create" ? "등록" : "저장"}</button><button type="button" className="secondary-button" onClick={closeDialog}>취소</button></div>
    </form></section> : null}
  </section>;
}
