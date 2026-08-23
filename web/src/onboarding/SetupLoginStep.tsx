import { useState, type SyntheticEvent } from "react";

export function SetupLoginStep({
  onLogin,
}: {
  onLogin: (username: string, password: string) => Promise<void>;
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  async function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    const oneTimePassword = password;
    setPassword("");
    await onLogin(username, oneTimePassword);
  }

  return (
    <section className="setup-card" aria-labelledby="setup-login-title">
      <p className="step-label">2 · 관리자 로그인</p>
      <h1 id="setup-login-title">생성한 관리자 계정으로 로그인</h1>
      <p>복구 코드를 보관한 뒤 비밀번호를 다시 입력하세요. 입력값은 저장되지 않습니다.</p>
      <form className="form-grid" onSubmit={(event) => { void submit(event); }}>
        <label htmlFor="setup-login-username">관리자 사용자 이름</label>
        <input id="setup-login-username" autoComplete="username" value={username} onChange={(event) => { setUsername(event.target.value); }} required />
        <label htmlFor="setup-login-password">관리자 비밀번호</label>
        <input id="setup-login-password" type="password" autoComplete="current-password" value={password} onChange={(event) => { setPassword(event.target.value); }} required />
        <button type="submit">로그인하고 설정 계속</button>
      </form>
    </section>
  );
}
