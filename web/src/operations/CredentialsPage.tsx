import { useState, type SyntheticEvent } from "react";

import { adminRequest } from "../api/client";
import { SecretOnceDialog } from "../components/SecretOnceDialog";
import { safeItemPath, textField, type OperationsProps } from "./operationTypes";
import { useAdminList } from "./useAdminList";

interface CredentialResponse {
  credential: string;
}

export function CredentialsPage({ role, csrfToken }: OperationsProps) {
  const allowed = role === "admin";
  const { items, failed, reload } = useAdminList(allowed ? "/credentials" : null);
  const [name, setName] = useState("");
  const [credential, setCredential] = useState<string | null>(null);
  const [saveFailed, setSaveFailed] = useState(false);

  if (!allowed) return <p role="alert">Client credential 관리는 admin만 수행할 수 있습니다.</p>;

  async function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    if (csrfToken === null) return;
    try {
      const issued = await adminRequest<CredentialResponse>("/credentials", { method: "POST", csrfToken, body: { name, scopes: ["mcp:invoke"] } });
      if (typeof issued.credential !== "string") throw new Error("invalid response");
      setCredential(issued.credential);
      setName("");
      setSaveFailed(false);
    } catch {
      setSaveFailed(true);
    }
  }

  async function revoke(selector: string) {
    if (csrfToken === null || !window.confirm("이 credential을 폐기하시겠습니까?")) return;
    await adminRequest(safeItemPath("credentials", selector), { method: "DELETE", csrfToken });
    await reload();
  }

  async function closeSecret() {
    setCredential(null);
    await reload();
  }

  return (
    <section aria-labelledby="credentials-title">
      <h1 id="credentials-title">Client credentials</h1>
      <p>발급된 원문은 한 번만 표시되며, 이 화면은 연결 성공을 의미하지 않습니다.</p>
      {failed ? <p role="alert">Credential 목록을 불러올 수 없습니다.</p> : null}
      {items ? <table><thead><tr><th>이름</th><th>Selector</th><th>상태</th><th>작업</th></tr></thead><tbody>{items.map((item) => { const selector = textField(item, "selector"); return <tr key={selector}><td>{textField(item, "name")}</td><td>{selector}</td><td>{textField(item, "revoked_at") === "—" ? "active" : "revoked"}</td><td><button type="button" onClick={() => { void revoke(selector); }}>폐기</button></td></tr>; })}</tbody></table> : null}
      {csrfToken ? <form className="form-grid compact-form" onSubmit={(event) => { void submit(event); }}><label htmlFor="operation-credential-name">credential 이름</label><input id="operation-credential-name" value={name} onChange={(event) => { setName(event.target.value); }} required />{saveFailed ? <p role="alert">Credential을 생성할 수 없습니다.</p> : null}<button type="submit">접근 credential 생성</button></form> : <p role="alert">변경하려면 다시 로그인하세요.</p>}
      {credential ? <SecretOnceDialog title="일회용 client credential" values={[credential]} closeLabel="확인하고 닫기" onClose={() => { void closeSecret(); }} /> : null}
    </section>
  );
}
