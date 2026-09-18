import { useState, type SyntheticEvent } from "react";
import {
  BrowserRouter,
  Navigate,
  NavLink,
  Route,
  Routes,
} from "react-router-dom";

import { useAuth } from "../auth/AuthProvider";
import { ConnectionsPage } from "../dependencies/ConnectionsPage";
import { TestLabPage } from "../dependencies/TestLabPage";
import { OnboardingShell } from "../onboarding/OnboardingShell";
import { PublishedSnapshotGuard } from "../onboarding/PublishedSnapshotGuard";
import { AuditEventsPage } from "../operations/AuditEventsPage";
import { CredentialsPage } from "../operations/CredentialsPage";
import { DashboardPage } from "../operations/DashboardPage";
import { ModelsPage } from "../operations/ModelsPage";
import { PoliciesPage } from "../operations/PoliciesPage";
import { ProvidersPage } from "../operations/ProvidersPage";
import { SnapshotsPage } from "../operations/SnapshotsPage";
import { SystemPage } from "../operations/SystemPage";

function LoginPage() {
  const auth = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [recoveryMode, setRecoveryMode] = useState(false);

  async function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    const currentPassword = password;
    setPassword("");
    await auth.login(username, currentPassword);
  }

  return (
    <main className="auth-layout">
      <section className="auth-card" aria-labelledby="login-title">
        <p className="eyebrow">Media Governance Gateway</p>
        <h1 id="login-title">Media Bridge 로그인</h1>
        <p>모델의 미디어 호환성과 안전 차단 상태를 관리합니다.</p>
        {auth.status === "totp_required" || auth.status === "totp_enrollment" ? (
          <form onSubmit={(event) => { event.preventDefault(); void (recoveryMode ? auth.loginWithRecoveryCode(code) : auth.verifyTotp(code)); }}>
            {auth.status === "totp_enrollment" ? <><p>인증 앱에 다음 키를 등록하세요: <code>{auth.secret}</code></p><p><code>{auth.provisioningUri}</code></p><button type="button" onClick={() => { void auth.confirmTotpEnrollment(code); }}>등록 확인</button></> : <button type="button" onClick={() => { void auth.beginTotpEnrollment(); }}>인증 앱 등록</button>}
            <label htmlFor="totp-code">인증 앱 코드</label>
            <input id="totp-code" inputMode="numeric" value={code} onChange={(event) => { setCode(event.target.value); }} required />
            <button type="submit">{recoveryMode ? "복구 코드 확인" : "코드 확인"}</button>
            {auth.status === "totp_required" ? <><button type="button" onClick={() => { void auth.requestRecoveryCode(); }}>복구 이메일 보내기</button><button type="button" onClick={() => { setRecoveryMode(!recoveryMode); }}>인증 앱 코드 / 복구 코드 전환</button></> : null}
          </form>
        ) : <form onSubmit={(event) => { void submit(event); }}>
          <label htmlFor="username">사용자 이름</label>
          <input
            id="username"
            autoComplete="username"
            value={username}
            onChange={(event) => { setUsername(event.target.value); }}
            required
          />
          <label htmlFor="password">비밀번호</label>
          <input
            id="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => { setPassword(event.target.value); }}
            required
          />
          {auth.status === "anonymous" && auth.errorCode !== "unauthorized" ? (
            <p role="alert">로그인 요청을 완료하지 못했습니다.</p>
          ) : null}
          <button type="submit">로그인</button>
        </form>}
      </section>
    </main>
  );
}

function ConsoleLayout() {
  const auth = useAuth();
  if (auth.status !== "authenticated") return null;
  return (
    <div className="app-shell">
      <header>
        <strong>Media Bridge</strong>
        <span>{auth.principal.username} · {auth.principal.role}</span>
      </header>
      <nav aria-label="주요 메뉴">
        <NavLink to="/">Dashboard</NavLink>
        <NavLink to="/providers">Providers</NavLink>
        <NavLink to="/models">Models</NavLink>
        <NavLink to="/policies">Policies</NavLink>
        {auth.principal.role === "admin" ? <NavLink to="/credentials">Credentials</NavLink> : null}
        {auth.principal.role === "admin" ? <NavLink to="/snapshots">Snapshots</NavLink> : null}
        <NavLink to="/audit">Audit &amp; Events</NavLink>
        <NavLink to="/system">System</NavLink>
        <NavLink to="/connections">Connections</NavLink>
        <NavLink to="/test-lab">Test Lab</NavLink>
      </nav>
      <main>
        <Routes>
          <Route path="/setup" element={<OnboardingShell />} />
          <Route element={<PublishedSnapshotGuard role={auth.principal.role} />}>
            <Route path="/" element={<DashboardPage role={auth.principal.role} />} />
            <Route path="/providers" element={<ProvidersPage role={auth.principal.role} csrfToken={auth.csrfToken} />} />
            <Route path="/models" element={<ModelsPage role={auth.principal.role} csrfToken={auth.csrfToken} />} />
            <Route path="/policies" element={<PoliciesPage role={auth.principal.role} csrfToken={auth.csrfToken} />} />
            <Route path="/credentials" element={<CredentialsPage role={auth.principal.role} csrfToken={auth.csrfToken} />} />
            <Route path="/snapshots" element={<SnapshotsPage role={auth.principal.role} csrfToken={auth.csrfToken} />} />
            <Route path="/audit" element={<AuditEventsPage />} />
            <Route path="/system" element={<SystemPage />} />
            <Route path="/connections" element={<ConnectionsPage role={auth.principal.role} csrfToken={auth.csrfToken} />} />
            <Route path="/test-lab" element={<TestLabPage role={auth.principal.role} csrfToken={auth.csrfToken} />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </main>
    </div>
  );
}

function AuthenticatedRoutes() {
  const auth = useAuth();
  if (auth.status === "loading") return <p role="status">세션을 확인하고 있습니다.</p>;
  if (auth.status === "anonymous") {
    return (
      <Routes>
        <Route path="/setup" element={<Navigate to="/login" replace />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    );
  }
  return (
    <Routes>
      <Route path="/login" element={<Navigate to="/" replace />} />
      <Route path="*" element={<ConsoleLayout />} />
    </Routes>
  );
}

export function ConsoleRouter() {
  return <BrowserRouter><AuthenticatedRoutes /></BrowserRouter>;
}
