import { useState, type SyntheticEvent } from "react";

import { adminRequest } from "../api/client";
import type { OperationsProps } from "../operations/operationTypes";
import { safeItemPath, textField } from "../operations/operationTypes";
import { useAdminList } from "../operations/useAdminList";

type SecretReferenceKind = "env" | "docker_secret" | "external";

const SECRET_REFERENCE_PATTERNS: Record<SecretReferenceKind, string> = {
  env: "[A-Z][A-Z0-9_]*",
  docker_secret: "[A-Za-z0-9][A-Za-z0-9_.-]*",
  external: "(vault|aws-sm|gcp-sm|azure-kv)://[A-Za-z0-9][A-Za-z0-9._/@:-]*",
};

function secretReference(item: Record<string, unknown>): string {
  const value = item.credential_secret_ref;
  if (typeof value !== "object" || value === null) return "—";
  const reference = value as Record<string, unknown>;
  return `${textField(reference, "kind")}: ${textField(reference, "identifier")}`;
}

export function ConnectionsPage({ role, csrfToken }: OperationsProps) {
  const { items, failed, reload } = useAdminList("/connections");
  const [name, setName] = useState("");
  const [gatewayUrl, setGatewayUrl] = useState("");
  const [secretReferenceKind, setSecretReferenceKind] = useState<SecretReferenceKind>("env");
  const [secretReferenceName, setSecretReferenceName] = useState("");
  const [actionError, setActionError] = useState(false);
  const adminWritable = role === "admin" && csrfToken !== null;
  const canTest = role !== "viewer" && csrfToken !== null;

  async function createConnection(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!adminWritable) return;
    const currentReference = secretReferenceName;
    setSecretReferenceName("");
    setActionError(false);
    try {
      await adminRequest("/connections", {
        method: "POST",
        csrfToken,
        body: {
          name,
          gateway_url: gatewayUrl,
          credential_secret_ref: {
            kind: secretReferenceKind,
            identifier: currentReference,
          },
          enabled: true,
        },
      });
      setName("");
      setGatewayUrl("");
      await reload();
    } catch {
      setActionError(true);
    }
  }

  async function testConnection(identifier: string) {
    if (!canTest) return;
    setActionError(false);
    try {
      await adminRequest(safeItemPath("connections", identifier, "/test"), {
        method: "POST",
        csrfToken,
      });
      await reload();
    } catch {
      setActionError(true);
    }
  }

  async function revokeConnection(identifier: string) {
    if (!adminWritable) return;
    setActionError(false);
    try {
      await adminRequest(safeItemPath("connections", identifier), {
        method: "DELETE",
        csrfToken,
      });
      await reload();
    } catch {
      setActionError(true);
    }
  }

  return (
    <section aria-labelledby="connections-title">
      <h1 id="connections-title">Connections</h1>
      <p>Gateway credential 원문이 아니라 외부 Secret 참조와 검증 상태만 관리합니다.</p>
      {failed ? <p role="alert">Connection 목록을 불러올 수 없습니다.</p> : null}
      {actionError ? <p role="alert">Connection 작업을 안전하게 완료하지 못했습니다.</p> : null}
      {items === null && !failed ? <p role="status">Connection 목록을 불러오고 있습니다.</p> : null}
      {items ? (
        <table>
          <thead><tr><th>이름</th><th>Gateway</th><th>Secret 참조</th><th>상태</th><th>마지막 성공</th><th>작업</th></tr></thead>
          <tbody>
            {items.map((item) => {
              const identifier = textField(item, "id");
              const revoked = textField(item, "status") === "revoked";
              return (
                <tr key={identifier}>
                  <td>{textField(item, "name")}</td>
                  <td>{textField(item, "gateway_url")}</td>
                  <td>{secretReference(item)}</td>
                  <td>{textField(item, "status")}</td>
                  <td>{textField(item, "last_success_at")}</td>
                  <td><div className="inline-actions">
                    {canTest ? <button className="secondary-button" type="button" disabled={revoked} onClick={() => { void testConnection(identifier); }}>연결 시험</button> : null}
                    {adminWritable ? <button type="button" disabled={revoked} onClick={() => { void revokeConnection(identifier); }}>폐기</button> : null}
                  </div></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      ) : null}
      {adminWritable ? (
        <form className="form-grid compact-form" onSubmit={(event) => { void createConnection(event); }}>
          <h2>Connection 추가</h2>
          <label htmlFor="connection-name">이름</label>
          <input id="connection-name" value={name} onChange={(event) => { setName(event.target.value); }} required />
          <label htmlFor="connection-url">Gateway HTTPS URL</label>
          <input id="connection-url" type="url" value={gatewayUrl} onChange={(event) => { setGatewayUrl(event.target.value); }} pattern="https://.*" required />
          <label htmlFor="connection-secret-kind">Secret 참조 종류</label>
          <select
            id="connection-secret-kind"
            value={secretReferenceKind}
            onChange={(event) => { setSecretReferenceKind(event.target.value as SecretReferenceKind); }}
          >
            <option value="env">환경변수 참조</option>
            <option value="docker_secret">Docker Secret</option>
            <option value="external">외부 Secret Store</option>
          </select>
          <label htmlFor="connection-secret-reference">Secret 식별자</label>
          <input
            id="connection-secret-reference"
            value={secretReferenceName}
            onChange={(event) => { setSecretReferenceName(event.target.value); }}
            pattern={SECRET_REFERENCE_PATTERNS[secretReferenceKind]}
            autoComplete="off"
            aria-describedby="connection-secret-help"
            required
          />
          <p id="connection-secret-help">credential 원문이 아니라 외부 Secret의 이름이나 URI만 입력하세요.</p>
          <button type="submit">Connection 추가</button>
        </form>
      ) : <p>{role === "operator" ? "operator는 연결 시험만 수행할 수 있습니다." : "viewer는 Connection을 읽기만 할 수 있습니다."}</p>}
    </section>
  );
}
