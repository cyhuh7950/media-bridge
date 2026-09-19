import { useState } from "react";
import { adminRequest } from "../api/client";
import { numberField, safeItemPath, textField, type OperationsProps } from "./operationTypes";
import { useAdminList } from "./useAdminList";
import { SafeApiError } from "../api/client";

interface DraftResponse {
  draft_id: string;
}

function publishErrorMessage(code: string): string {
  if (code === "csrf_rejected") return "로그인 보안 토큰이 만료되었거나 일치하지 않습니다. 로그아웃 후 다시 로그인하세요.";
  if (code === "configuration_incomplete") return "Provider와 정책을 확인하세요. Provider 기준 모델이나 catalog 기본 모델이 필요하고 정책은 정확히 1개여야 합니다. 모델 별도 등록은 선택 사항입니다.";
  return `발행할 수 없습니다. (${code})`;
}

export function SnapshotsPage({ role, csrfToken }: OperationsProps) {
  const allowed = role === "admin";
  const { items, failed, reload } = useAdminList(allowed ? "/snapshots" : null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!allowed) return <p role="alert">Snapshot 발행과 rollback은 admin만 수행할 수 있습니다.</p>;

  async function publish() {
    if (csrfToken === null || busy) return;
    setBusy(true);
    setError(null);
    try {
      const draft = await adminRequest<DraftResponse>("/drafts/validate", { method: "POST", csrfToken, body: {} });
      await adminRequest("/snapshots", { method: "POST", csrfToken, body: { draft_id: draft.draft_id } });
      await reload();
    } catch (cause) {
      setError(cause instanceof SafeApiError ? publishErrorMessage(cause.code) : "발행할 수 없습니다. 잠시 후 다시 시도하세요.");
    } finally {
      setBusy(false);
    }
  }

  async function rollback(version: number) {
    if (csrfToken === null || !window.confirm(`snapshot version ${String(version)}으로 rollback하시겠습니까?`)) return;
    await adminRequest(safeItemPath("snapshots", String(version), "/rollback"), { method: "POST", csrfToken, body: {} });
    await reload();
  }

  return (
    <section aria-labelledby="snapshots-title">
      <h1 id="snapshots-title">스냅샷</h1>
      <p>검증된 draft만 서명 snapshot으로 발행할 수 있습니다.</p>
      {failed ? <p role="alert">Snapshot 목록을 불러올 수 없습니다.</p> : null}
      {error ? <p role="alert">{error}</p> : null}
      {items ? <table><thead><tr><th>Version</th><th>생성 시각</th><th>작업</th></tr></thead><tbody>{items.map((item) => { const version = numberField(item, "version"); return <tr key={version ?? textField(item, "snapshot_id")} aria-label={`version ${version === null ? "unknown" : String(version)}`}><td>{version ?? "—"}</td><td>{textField(item, "created_at")}</td><td>{version === null ? null : <button type="button" onClick={() => { void rollback(version); }}>이 버전으로 rollback</button>}</td></tr>; })}</tbody></table> : null}
      {csrfToken ? <button type="button" disabled={busy} onClick={() => { void publish(); }}>{busy ? "검증 및 발행 중…" : "현재 설정 검증 및 발행"}</button> : <p role="alert">변경하려면 다시 로그인하세요.</p>}
    </section>
  );
}


