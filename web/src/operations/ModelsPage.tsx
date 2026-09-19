import { useState, type SyntheticEvent } from "react";

import { adminRequest } from "../api/client";
import { textField, type OperationsProps } from "./operationTypes";
import { useAdminList } from "./useAdminList";

type Model = Record<string, unknown>;

export function ModelsPage({ role, csrfToken }: OperationsProps) {
  const { items, failed, reload } = useAdminList("/models");
  const { items: providers } = useAdminList("/providers");
  const llmProviders = (providers ?? []).filter((provider) => textField(provider, "kind") === "llm");
  const [dialog, setDialog] = useState<"create" | "edit" | null>(null);
  const [editingId, setEditingId] = useState("");
  const [providerId, setProviderId] = useState("");
  const [modelId, setModelId] = useState("");
  const [evidence, setEvidence] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [actionFailed, setActionFailed] = useState(false);
  const writable = role !== "viewer" && csrfToken !== null;
  const allSelected = !!items?.length && selected.length === items.length;

  function openCreate() { setDialog("create"); setEditingId(""); setProviderId(""); setModelId(""); setEvidence(""); setActionFailed(false); }
  function openEdit(item: Model) { setDialog("edit"); setEditingId(textField(item, "id")); setProviderId(textField(item, "provider_id")); setModelId(textField(item, "model_id")); setEvidence(textField(item, "evidence")); setActionFailed(false); }
  async function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!writable || !dialog || !providerId) return;
    try {
      const now = new Date();
      const body = { provider_id: providerId, model_id: modelId, aliases: [], input_modalities: ["text"], evidence, reviewed_at: now.toISOString(), expires_at: new Date(now.getTime() + 30 * 86400000).toISOString(), pdf_passthrough_verified: false };
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
    <div className="page-heading"><div><h1 id="models-title">모델 관리</h1><p>Non-Vision LLM Provider별 모델과 capability를 관리합니다.</p></div>{writable ? <button type="button" onClick={openCreate}>모델 등록</button> : null}</div>
    {failed ? <p role="alert">모델 목록을 불러올 수 없습니다.</p> : null}{actionFailed ? <p role="alert">모델 작업을 완료하지 못했습니다.</p> : null}
    {items?.length === 0 && !failed ? <p role="status">등록된 모델이 없습니다.</p> : null}
    {items && items.length > 0 ? <>
      {writable && selected.length ? <div className="inline-actions"><button type="button" className="danger-button" onClick={() => { void removeSelected(); }}>선택 삭제 ({selected.length})</button></div> : null}
      <table><thead><tr>{writable ? <th><input aria-label="전체 모델 선택" type="checkbox" checked={allSelected} onChange={(e) => { setSelected(e.target.checked ? items.map((i) => textField(i, "id")) : []); }} /></th> : null}<th>Provider</th><th>모델 ID</th><th>근거</th><th>만료</th>{writable ? <th>작업</th> : null}</tr></thead><tbody>
        {items.map((item) => { const id = textField(item, "id"); return <tr key={id}>{writable ? <td><input aria-label={`${textField(item, "model_id")} 선택`} type="checkbox" checked={selected.includes(id)} onChange={(e) => { setSelected((current) => e.target.checked ? [...current, id] : current.filter((value) => value !== id)); }} /></td> : null}<td>{providerName(item)}</td><td>{textField(item, "model_id")}</td><td>{textField(item, "evidence")}</td><td>{textField(item, "expires_at")}</td>{writable ? <td><button type="button" className="secondary-button" onClick={() => { openEdit(item); }}>수정</button></td> : null}</tr>; })}
      </tbody></table>
    </> : null}
    {!writable ? <p>viewer는 모델 설정을 읽기만 할 수 있습니다.</p> : null}
    {dialog ? <section className="dialog-backdrop" role="dialog" aria-modal="true" aria-labelledby="model-dialog-title"><form className="dialog-card form-grid" onSubmit={(e) => { void submit(e); }}><h2 id="model-dialog-title">{dialog === "create" ? "모델 등록" : "모델 수정"}</h2><label htmlFor="operation-model-provider">LLM Provider</label><select id="operation-model-provider" value={providerId} onChange={(e) => { setProviderId(e.target.value); }} required><option value="">Provider를 선택하세요</option>{llmProviders.map((provider) => <option key={textField(provider, "id")} value={textField(provider, "id")}>{textField(provider, "name")}</option>)}</select><label htmlFor="operation-model-id">모델 ID</label><input id="operation-model-id" value={modelId} onChange={(e) => { setModelId(e.target.value); }} required /><label htmlFor="operation-model-evidence">Capability 근거</label><textarea id="operation-model-evidence" value={evidence} onChange={(e) => { setEvidence(e.target.value); }} required /><p>Provider가 제공하는 실제 모델 ID와 텍스트 전용 여부를 확인한 근거를 입력하세요.</p><div className="inline-actions"><button type="submit" disabled={!providerId}>{dialog === "create" ? "등록" : "저장"}</button><button type="button" className="secondary-button" onClick={() => { setDialog(null); }}>취소</button></div></form></section> : null}
  </section>;
}
