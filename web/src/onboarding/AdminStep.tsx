import { useState, type SyntheticEvent } from "react";

import { adminRequest, SafeApiError } from "../api/client";
import { SecretOnceDialog } from "../components/SecretOnceDialog";

interface BootstrapResponse {
  recovery_codes: string[];
}

export function AdminStep({
  onComplete,
}: {
  onComplete: () => void;
}) {
  const [bootstrapToken, setBootstrapToken] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [recoveryCodes, setRecoveryCodes] = useState<string[] | null>(null);
  const [errorCode, setErrorCode] = useState<string | null>(null);

  async function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    const oneTimeToken = bootstrapToken;
    const oneTimePassword = password;
    setBootstrapToken("");
    setPassword("");
    setErrorCode(null);
    try {
      const response = await adminRequest<BootstrapResponse>("/bootstrap", {
        method: "POST",
        bootstrapToken: oneTimeToken,
        body: { username, password: oneTimePassword },
      });
      if (!Array.isArray(response.recovery_codes)) {
        throw new SafeApiError(502, "invalid_response");
      }
      setRecoveryCodes([...response.recovery_codes]);
    } catch (error: unknown) {
      setErrorCode(error instanceof SafeApiError ? error.code : "request_failed");
    }
  }

  return (
    <section className="setup-card" aria-labelledby="admin-step-title">
      <p className="step-label">2 · 최초 관리자</p>
      <h1 id="admin-step-title">관리자 계정 설정</h1>
      <p>서버에서 별도로 발급한 15분 일회용 bootstrap token을 입력하세요.</p>
      <form className="form-grid" onSubmit={(event) => { void submit(event); }}>
        <label htmlFor="bootstrap-token">bootstrap token</label>
        <input id="bootstrap-token" type="password" value={bootstrapToken} onChange={(event) => { setBootstrapToken(event.target.value); }} required />
        <label htmlFor="admin-username">관리자 사용자 이름</label>
        <input id="admin-username" autoComplete="username" value={username} onChange={(event) => { setUsername(event.target.value); }} required />
        <label htmlFor="admin-password">관리자 비밀번호</label>
        <input id="admin-password" type="password" autoComplete="new-password" minLength={12} value={password} onChange={(event) => { setPassword(event.target.value); }} required />
        {errorCode ? <p role="alert">관리자 계정을 생성할 수 없습니다.</p> : null}
        <button type="submit">최초 관리자 생성</button>
      </form>
      {recoveryCodes ? (
        <SecretOnceDialog
          title="일회용 복구 코드"
          values={recoveryCodes}
          closeLabel="복구 코드를 보관했습니다"
          onClose={() => {
            setRecoveryCodes(null);
            onComplete();
          }}
        />
      ) : null}
    </section>
  );
}
