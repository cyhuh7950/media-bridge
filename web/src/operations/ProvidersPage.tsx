import { useEffect, useState, type SyntheticEvent } from "react";

import { adminRequest } from "../api/client";
import type { ProviderReasoningOptions, ProviderWriteRequest, ReasoningEffort } from "../api/contracts";
import { ProviderCatalogPicker, type ProviderCatalogEntry, type ManagedProviderKind } from "../providers/ProviderCatalogPicker";
import { booleanField, textField, type OperationsProps } from "./operationTypes";
import { useAdminList } from "./useAdminList";

function providerKindLabel(value: string): string {
  return value === "analysis" ? "분석" : value === "llm" ? "Non‑Vision LLM" : value;
}

type DialogMode = "create" | "edit";

function asReasoningEffort(value: unknown): ReasoningEffort {
  return value === "none" || value === "minimal" || value === "low" || value === "medium" || value === "high" || value === "xhigh"
    ? value
    : "provider_default";
}

export function ProvidersPage({ role, csrfToken }: OperationsProps) {
  const { items, failed, reload } = useAdminList("/providers");
  const [dialogMode, setDialogMode] = useState<DialogMode | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [name, setName] = useState("");
  const [alias, setAlias] = useState("");
  const [kind, setKind] = useState<ManagedProviderKind>("analysis");
  const [catalogId, setCatalogId] = useState("");
  const [modelId, setModelId] = useState("");
  const [protocol, setProtocol] = useState("");
  const [capabilities, setCapabilities] = useState<string[]>([]);
  const [endpoint, setEndpoint] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [reasoningEffort, setReasoningEffort] = useState<ReasoningEffort>("provider_default");
  const [reasoningOptionsResult, setReasoningOptionsResult] = useState<{
    query: string;
    efforts: ReasoningEffort[];
  } | null>(null);
  const [saveFailed, setSaveFailed] = useState(false);
  const [deleteFailed, setDeleteFailed] = useState(false);
  const writable = role !== "viewer" && csrfToken !== null;
  const allSelected = items !== null && items.length > 0 && selectedIds.length === items.length;
  const reasoningOptionsQuery = dialogMode !== null && kind === "llm" && catalogId && protocol && modelId.trim()
    ? new URLSearchParams({ catalog_id: catalogId, protocol, model_id: modelId.trim() }).toString()
    : null;
  const reasoningOptions: ReasoningEffort[] = reasoningOptionsQuery !== null && reasoningOptionsResult?.query === reasoningOptionsQuery
    ? reasoningOptionsResult.efforts
    : ["provider_default"];
  const reasoningOptionsLoading = reasoningOptionsQuery !== null && reasoningOptionsResult?.query !== reasoningOptionsQuery;
  const unsupportedReasoningEffort = kind === "llm" && !reasoningOptionsLoading && !reasoningOptions.includes(reasoningEffort);

  useEffect(() => {
    if (reasoningOptionsQuery === null) return;
    let active = true;
    void adminRequest<ProviderReasoningOptions>(`/provider-reasoning-options?${reasoningOptionsQuery}`)
      .then((payload) => {
        if (active) {
          const efforts: ReasoningEffort[] = Array.isArray(payload.efforts) && payload.efforts.includes("provider_default")
            ? payload.efforts
            : ["provider_default"];
          setReasoningOptionsResult({ query: reasoningOptionsQuery, efforts });
        }
      })
      .catch(() => {
        if (active) setReasoningOptionsResult({ query: reasoningOptionsQuery, efforts: ["provider_default"] });
      });
    return () => { active = false; };
  }, [reasoningOptionsQuery]);

  function closeDialog() {
    setDialogMode(null);
    setEditingId(null);
    setSaveFailed(false);
    setApiKey("");
    setReasoningEffort("provider_default");
  }

  function openCreate() {
    setEditingId(null); setDialogMode("create"); setName(""); setAlias(""); setKind("analysis"); setCatalogId(""); setModelId(""); setProtocol(""); setCapabilities([]); setEndpoint(""); setApiKey(""); setReasoningEffort("provider_default"); setSaveFailed(false);
  }

  function openEdit(item: Record<string, unknown>) {
    const savedModel = typeof item.model_id === "string" ? item.model_id : "";
    setEditingId(textField(item, "id")); setDialogMode("edit"); setName(textField(item, "name")); setAlias(textField(item, "alias").toLowerCase()); setKind(textField(item, "kind") === "llm" ? "llm" : "analysis"); setCatalogId(textField(item, "catalog_id")); setModelId(savedModel); setProtocol(textField(item, "protocol")); setCapabilities(Array.isArray(item.capabilities) ? item.capabilities.filter((value): value is string => typeof value === "string") : []); setEndpoint(textField(item, "endpoint")); setReasoningEffort(asReasoningEffort(item.reasoning_effort)); setApiKey(""); setSaveFailed(false);
  }

  async function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!writable) return;
    setSaveFailed(false);
    try {
      if (reasoningOptionsLoading || unsupportedReasoningEffort) return;
      const body: ProviderWriteRequest & Record<string, unknown> = { name, alias: alias.trim().toLowerCase() || undefined, kind, catalog_id: catalogId && catalogId !== "__custom__" ? catalogId : undefined, model_id: modelId || undefined, endpoint, protocol: protocol || undefined, capabilities, reasoning_effort: kind === "llm" ? reasoningEffort : undefined, secret_ref: { kind: "db", identifier: "provider_api_key" }, api_key: apiKey || undefined, enabled: true };
      if (dialogMode === "edit" && editingId) await adminRequest(`/providers/${editingId}`, { method: "PATCH", csrfToken, body });
      else await adminRequest("/providers", { method: "POST", csrfToken, body });
      closeDialog(); await reload();
    } catch { setSaveFailed(true); }
  }

  function toggleSelected(id: string, checked: boolean) { setSelectedIds((current) => checked ? [...new Set([...current, id])] : current.filter((value) => value !== id)); }

  async function deleteSelected() {
    if (!writable || selectedIds.length === 0 || !window.confirm("선택한 Provider를 삭제하시겠습니까?")) return;
    setDeleteFailed(false);
    try { await Promise.all(selectedIds.map((id) => adminRequest(`/providers/${id}`, { method: "DELETE", csrfToken }))); setSelectedIds([]); await reload(); }
    catch { setDeleteFailed(true); }
  }

  return (
    <section aria-labelledby="providers-title">
      <div className="page-heading"><div><h1 id="providers-title">Provider 관리</h1><p>분석 Provider와 Non‑Vision LLM Provider를 관리합니다.</p></div>{writable ? <button type="button" onClick={openCreate}>Provider 등록</button> : null}</div>
      {failed ? <p role="alert">Provider 목록을 불러올 수 없습니다.</p> : null}
      {deleteFailed ? <p role="alert">선택한 Provider를 모두 삭제하지 못했습니다.</p> : null}
      {!writable ? <p>viewer는 Provider 설정을 읽기만 할 수 있습니다.</p> : null}
      {items === null && !failed ? <p role="status">Provider 목록을 불러오고 있습니다.</p> : null}
      {items ? <>
        {writable && selectedIds.length > 0 ? <div className="inline-actions"><button type="button" className="danger-button" onClick={() => { void deleteSelected(); }}>선택 삭제 ({selectedIds.length})</button></div> : null}
        <table><thead><tr>{writable ? <th><input aria-label="전체 Provider 선택" type="checkbox" checked={allSelected} onChange={(event) => { setSelectedIds(event.target.checked ? items.map((item) => textField(item, "id")) : []); }} /></th> : null}<th>이름</th><th>종류</th><th>엔드포인트</th><th>상태</th><th>수정자</th><th>수정일시</th>{writable ? <th>작업</th> : null}</tr></thead>
          <tbody>{items.map((item) => { const id = textField(item, "id"); return <tr key={id}>{writable ? <td><input aria-label={`${textField(item, "name")} 선택`} type="checkbox" checked={selectedIds.includes(id)} onChange={(event) => { toggleSelected(id, event.target.checked); }} /></td> : null}<td>{textField(item, "name")}</td><td>{providerKindLabel(textField(item, "kind"))}</td><td>{textField(item, "endpoint")}</td><td>{booleanField(item, "enabled") === true ? "활성" : "비활성"}</td><td>{textField(item, "updated_by") || "—"}</td><td>{textField(item, "updated_at") || "—"}</td>{writable ? <td><button type="button" className="secondary-button" onClick={() => { openEdit(item); }}>수정</button></td> : null}</tr>; })}</tbody>
        </table>
      </> : null}
      {dialogMode ? <section className="dialog-backdrop" role="dialog" aria-modal="true" aria-labelledby="provider-dialog-title"><form className="dialog-card form-grid" onSubmit={(event) => { void submit(event); }}><h2 id="provider-dialog-title">{dialogMode === "create" ? "Provider 등록" : "Provider 수정"}</h2>
        <label htmlFor="provider-operation-kind">Provider 유형</label><select id="provider-operation-kind" value={kind} onChange={(event) => { setKind(event.target.value as ManagedProviderKind); setCatalogId(""); setReasoningEffort("provider_default"); }}><option value="analysis">분석 Provider</option><option value="llm">Non-Vision LLM Provider</option></select>
        <ProviderCatalogPicker kind={kind} value={catalogId} onChange={(entry: ProviderCatalogEntry | null) => { setCatalogId(entry?.provider_id ?? "__custom__"); setName(entry?.provider_id ?? ""); setAlias(entry?.provider_id?.replace(/[^a-z0-9]+/g, "-") ?? ""); setModelId(entry?.default_model_id ?? ""); setEndpoint(entry?.default_endpoint ?? ""); setProtocol(entry?.protocol ?? "openai-chat-completions"); setCapabilities(entry?.capabilities ?? ["text"]); setReasoningEffort("provider_default"); }} />
        <label htmlFor="provider-operation-name">Provider 이름</label><input id="provider-operation-name" value={name} onChange={(event) => { setName(event.target.value); }} required />
        <label htmlFor="provider-operation-alias">Provider 약어</label><input id="provider-operation-alias" value={alias} onChange={(event) => { setAlias(event.target.value.toLowerCase()); }} placeholder="자동 생성되며 수정할 수 있습니다" required />
        <label htmlFor="provider-operation-model">기준 모델 (선택)</label><input id="provider-operation-model" value={modelId} onChange={(event) => { setModelId(event.target.value); }} placeholder="비워두면 Provider 기준 모델 사용" />
        {kind === "llm" && catalogId && protocol && modelId.trim() ? <><label htmlFor="provider-operation-reasoning">추론 등급</label><select id="provider-operation-reasoning" value={reasoningEffort} onChange={(event) => { setReasoningEffort(asReasoningEffort(event.target.value)); }} disabled={reasoningOptionsLoading}><option value="provider_default">Provider 기본값</option>{reasoningOptions.filter((value) => value !== "provider_default").map((value) => <option key={value} value={value}>{value}</option>)}{unsupportedReasoningEffort ? <option value={reasoningEffort}>현재 저장값 · 미지원 ({reasoningEffort})</option> : null}</select>{unsupportedReasoningEffort ? <p role="alert">현재 저장된 추론 등급은 이 모델에서 지원되지 않습니다. 지원 등급이나 Provider 기본값을 선택해야 합니다.</p> : null}</> : null}
        <label htmlFor="provider-operation-endpoint">HTTPS endpoint</label><input id="provider-operation-endpoint" type="url" value={endpoint} onChange={(event) => { setEndpoint(event.target.value); }} required />
        <label htmlFor="provider-operation-api-key">Provider API 키 {dialogMode === "edit" ? "(변경 시 입력)" : "(선택)"}</label><input id="provider-operation-api-key" type="password" value={apiKey} onChange={(event) => { setApiKey(event.target.value); }} autoComplete="new-password" />
        {saveFailed ? <p role="alert">Provider를 저장할 수 없습니다.</p> : null}<div className="inline-actions"><button type="submit" disabled={reasoningOptionsLoading || unsupportedReasoningEffort}>{dialogMode === "create" ? "등록" : "저장"}</button><button type="button" className="secondary-button" onClick={closeDialog}>취소</button></div>
      </form></section> : null}
    </section>
  );
}
