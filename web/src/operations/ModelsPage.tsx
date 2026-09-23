import { useState, type SyntheticEvent } from "react";

import { adminRequest } from "../api/client";
import { textField, type OperationsProps } from "./operationTypes";
import { useAdminList } from "./useAdminList";

type Model = Record<string, unknown>;

export function ModelsPage({ role, csrfToken }: OperationsProps) {
  const { items, failed, reload } = useAdminList("/models");
  const { items: providers } = useAdminList("/providers");
  const { items: routes } = useAdminList("/routing-profiles");
  const [dialog, setDialog] = useState<"create" | "edit" | null>(null);
  const [editingId, setEditingId] = useState("");
  const [providerId, setProviderId] = useState("");
  const [routingProfileId, setRoutingProfileId] = useState("");
  const [modelId, setModelId] = useState("");
  const [reasoningEffort, setReasoningEffort] = useState("provider_default");
  const [evidence, setEvidence] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [actionFailed, setActionFailed] = useState(false);
  const writable = role !== "viewer" && csrfToken !== null;
  const allSelected = !!items?.length && selected.length === items.length;
  const selectedRoute = (routes ?? []).find((item) => textField(item, "id") === routingProfileId);
  const routeProviderIds = Array.isArray(selectedRoute?.llm_provider_ids) ? selectedRoute.llm_provider_ids.filter((item): item is string => typeof item === "string") : [];
  const llmProviders = (providers ?? []).filter((provider) => textField(provider, "kind") === "llm" && (routeProviderIds.length === 0 || routeProviderIds.includes(textField(provider, "id"))));

  function openCreate() { setDialog("create"); setEditingId(""); setRoutingProfileId(""); setProviderId(""); setModelId(""); setReasoningEffort("provider_default"); setEvidence(""); setActionFailed(false); }
  function openEdit(item: Model) { setDialog("edit"); setEditingId(textField(item, "id")); setRoutingProfileId(textField(item, "routing_profile_id")); setProviderId(textField(item, "provider_id")); setModelId(textField(item, "model_id")); setReasoningEffort(textField(item, "reasoning_effort") || "provider_default"); setEvidence(textField(item, "evidence")); setActionFailed(false); }
  async function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!writable || !dialog || !providerId || !routingProfileId) return;
    try {
      const now = new Date();
      const body = { routing_profile_id: routingProfileId, provider_id: providerId, model_id: modelId.includes("/") ? modelId : modelId, aliases: [], input_modalities: ["text"], evidence, reviewed_at: now.toISOString(), expires_at: new Date(now.getTime() + 30 * 86400000).toISOString(), pdf_passthrough_verified: false, reasoning_effort: reasoningEffort };
      if (dialog === "edit") await adminRequest(`/models/${editingId}`, { method: "PATCH", csrfToken, body });
      else await adminRequest("/models", { method: "POST", csrfToken, body });
      setDialog(null); await reload();
    } catch { setActionFailed(true); }
  }
  async function removeSelected() {
    if (!writable || !selected.length || !window.confirm("선택한 모델을 삭제하시겠습니까?")) return;
    try { await Promise.all(selected.map((id) => adminRequest(`/models/${id}`, { method: "DELETE", csrfToken }))); setSelected([]); await reload(); } catch { setActionFailed(true); }
  }
  function providerName(item: Model) {
    const provider = (providers ?? []).find((candidate) => textField(candidate, "id") === textField(item, "provider_id"));
    return provider ? textField(provider, "name") : "Provider 미지정";
  }
  return <section aria-labelledby="models-title">
    <div className="page-heading"><div><h1 id="models-title">모델 관리</h1><p>내부 라우팅에 공개할 OpenAI 호환 모델을 생성합니다. Provider 등록만으로는 공개되지 않습니다.</p></div>{writable ? <button type="button" onClick={openCreate}>모델 생성</button> : null}</div>
    {failed ? <p role="alert">모델 목록을 불러올 수 없습니다.</p> : null}{actionFailed ? <p role="alert">모델 작업을 완료하지 못했습니다.</p> : null}
    {items?.length === 0 && !failed ? <p role="status">등록된 모델이 없습니다.</p> : null}
    {items && items.length > 0 ? <>
      {writable && selected.length ? <div className="inline-actions"><button type="button" className="danger-button" onClick={() => { void removeSelected(); }}>선택 삭제 ({selected.length})</button></div> : null}
      <table><thead><tr>{writable ? <th><input aria-label="전체 모델 선택" type="checkbox" checked={allSelected} onChange={(e) => { setSelected(e.target.checked ? items.map((i) => textField(i, "id")) : []); }} /></th> : null}<th>공개 모델</th><th>내부 라우팅</th><th>Provider</th><th>추론 등급</th><th>만료</th>{writable ? <th>작업</th> : null}</tr></thead><tbody>
        {items.map((item) => { const id = textField(item, "id"); return <tr key={id}>{writable ? <td><input aria-label={`${textField(item, "model_id")} 선택`} type="checkbox" checked={selected.includes(id)} onChange={(e) => { setSelected((current) => e.target.checked ? [...current, id] : current.filter((value) => value !== id)); }} /></td> : null}<td>{textField(item, "model_id")}</td><td>{textField(item, "routing_profile_id") || "기본"}</td><td>{providerName(item)}</td><td>{textField(item, "reasoning_effort") || "provider_default"}</td><td>{textField(item, "expires_at")}</td>{writable ? <td><button type="button" className="secondary-button" onClick={() => { openEdit(item); }}>수정</button></td> : null}</tr>; })}
      </tbody></table>
    </> : null}
    {!writable ? <p>viewer는 모델 설정을 읽기만 할 수 있습니다.</p> : null}
    {dialog ? <section className="dialog-backdrop" role="dialog" aria-modal="true" aria-labelledby="model-dialog-title"><form className="dialog-card form-grid" onSubmit={(e) => { void submit(e); }}><h2 id="model-dialog-title">{dialog === "create" ? "모델 생성" : "모델 수정"}</h2><label htmlFor="operation-model-route">내부 실행 라우팅</label><select id="operation-model-route" value={routingProfileId} onChange={(e) => { setRoutingProfileId(e.target.value); setProviderId(""); }} required><option value="">라우팅을 선택하세요</option>{(routes ?? []).filter((item) => item.enabled !== false).map((item) => <option key={textField(item, "id")} value={textField(item, "id")}>{textField(item, "name")}</option>)}</select><label htmlFor="operation-model-provider">기준 Non-Vision LLM Provider</label><select id="operation-model-provider" value={providerId} onChange={(e) => { setProviderId(e.target.value); }} required><option value="">Provider를 선택하세요</option>{llmProviders.map((provider) => <option key={textField(provider, "id")} value={textField(provider, "id")}>{textField(provider, "name")} ({textField(provider, "alias")})</option>)}</select><label htmlFor="operation-model-id">공개 모델 ID</label><input id="operation-model-id" value={modelId} onChange={(e) => { setModelId(e.target.value); }} placeholder="provider/model 형식" required /><label htmlFor="operation-model-reasoning">기본 추론 등급</label><select id="operation-model-reasoning" value={reasoningEffort} onChange={(e) => { setReasoningEffort(e.target.value); }}><option value="provider_default">Provider 설정 사용</option><option value="low">low</option><option value="medium">medium</option><option value="high">high</option></select><label htmlFor="operation-model-evidence">Capability 근거</label><textarea id="operation-model-evidence" value={evidence} onChange={(e) => { setEvidence(e.target.value); }} required /><div className="inline-actions"><button type="submit" disabled={!providerId || !routingProfileId}>{dialog === "create" ? "생성" : "저장"}</button><button type="button" className="secondary-button" onClick={() => { setDialog(null); }}>취소</button></div></form></section> : null}
  </section>;
}
