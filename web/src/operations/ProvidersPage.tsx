import { useState, type SyntheticEvent } from "react";

import { adminRequest } from "../api/client";
import { booleanField, textField, type OperationsProps } from "./operationTypes";
import { useAdminList } from "./useAdminList";

function providerReference(provider: Record<string, unknown>): string {
  const reference = provider.secret_ref;
  if (typeof reference !== "object" || reference === null) return "—";
  const fields = reference as Record<string, unknown>;
  return `${textField(fields, "kind")}: ${textField(fields, "identifier")}`;
}

export function ProvidersPage({ role, csrfToken }: OperationsProps) {
  const { items, failed, reload } = useAdminList("/providers");
  const [name, setName] = useState("");
  const [endpoint, setEndpoint] = useState("");
  const [reference, setReference] = useState("");
  const [saveFailed, setSaveFailed] = useState(false);
  const writable = role !== "viewer" && csrfToken !== null;

  async function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!writable) return;
    setSaveFailed(false);
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
      setName("");
      setEndpoint("");
      setReference("");
      await reload();
    } catch {
      setSaveFailed(true);
    }
  }

  return (
    <section aria-labelledby="providers-title">
      <h1 id="providers-title">Providers</h1>
      <p>Secret 원문 대신 외부 Secret 참조만 관리합니다.</p>
      {failed ? <p role="alert">Provider 목록을 불러올 수 없습니다.</p> : null}
      {items === null && !failed ? <p role="status">Provider 목록을 불러오고 있습니다.</p> : null}
      {items ? (
        <table><thead><tr><th>이름</th><th>종류</th><th>Endpoint</th><th>Secret 참조</th><th>상태</th></tr></thead>
          <tbody>{items.map((item) => <tr key={textField(item, "id")}><td>{textField(item, "name")}</td><td>{textField(item, "kind")}</td><td>{textField(item, "endpoint")}</td><td>{providerReference(item)}</td><td>{booleanField(item, "enabled") === true ? "enabled" : "disabled"}</td></tr>)}</tbody>
        </table>
      ) : null}
      {writable ? (
        <form className="form-grid compact-form" onSubmit={(event) => { void submit(event); }}>
          <h2>Provider 추가</h2>
          <label htmlFor="provider-operation-name">Provider 이름</label>
          <input id="provider-operation-name" value={name} onChange={(event) => { setName(event.target.value); }} required />
          <label htmlFor="provider-operation-endpoint">HTTPS endpoint</label>
          <input id="provider-operation-endpoint" type="url" value={endpoint} onChange={(event) => { setEndpoint(event.target.value); }} required />
          <label htmlFor="provider-operation-reference">Secret 환경변수 이름</label>
          <input id="provider-operation-reference" value={reference} onChange={(event) => { setReference(event.target.value); }} pattern="[A-Z][A-Z0-9_]*" required />
          {saveFailed ? <p role="alert">Provider를 저장할 수 없습니다.</p> : null}
          <button type="submit">Provider 추가</button>
        </form>
      ) : <p>viewer는 Provider 설정을 읽기만 할 수 있습니다.</p>}
    </section>
  );
}
