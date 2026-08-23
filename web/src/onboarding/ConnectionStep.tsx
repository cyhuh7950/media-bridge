import { useState, type SyntheticEvent } from "react";

import { adminRequest } from "../api/client";
import { SecretOnceDialog } from "../components/SecretOnceDialog";

interface CredentialResponse {
  credential: string;
}

export function ConnectionStep({ csrfToken, onSaved }: { csrfToken: string; onSaved: () => Promise<void> }) {
  const [name, setName] = useState("");
  const [credential, setCredential] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  async function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      const response = await adminRequest<CredentialResponse>("/credentials", {
        method: "POST",
        csrfToken,
        body: { name, scopes: ["mcp:invoke"] },
      });
      if (typeof response.credential !== "string") throw new Error("invalid response");
      setCredential(response.credential);
    } catch {
      setFailed(true);
    }
  }

  async function close() {
    setCredential(null);
    await onSaved();
  }

  return (
    <section className="setup-card" aria-labelledby="credential-step-title">
      <p className="step-label">6 · 접근 credential</p>
      <h1 id="credential-step-title">접근 credential 생성</h1>
      <p>이 단계는 연결 성공을 의미하지 않습니다. 실제 연결 시험은 P3 이후 제공됩니다.</p>
      <form className="form-grid" onSubmit={(event) => { void submit(event); }}>
        <label htmlFor="credential-name">credential 이름</label>
        <input id="credential-name" value={name} onChange={(event) => { setName(event.target.value); }} required />
        {failed ? <p role="alert">credential을 생성할 수 없습니다.</p> : null}
        <button type="submit">credential 생성</button>
      </form>
      {credential ? (
        <SecretOnceDialog
          title="일회용 client credential"
          values={[credential]}
          closeLabel="확인하고 닫기"
          onClose={() => { void close(); }}
        />
      ) : null}
    </section>
  );
}
