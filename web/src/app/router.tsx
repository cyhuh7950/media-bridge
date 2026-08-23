import { useState, type SyntheticEvent } from "react";
import {
  BrowserRouter,
  Navigate,
  NavLink,
  Route,
  Routes,
} from "react-router-dom";

import { useAuth } from "../auth/AuthProvider";

function LoginPage() {
  const auth = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

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
        <form onSubmit={(event) => { void submit(event); }}>
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
        </form>
      </section>
    </main>
  );
}

function Dashboard() {
  return (
    <section aria-labelledby="dashboard-title">
      <p className="eyebrow">Control Plane</p>
      <h1 id="dashboard-title">Dashboard</h1>
      <p>실제 Admin API 상태를 불러오는 중립적인 운영 화면입니다.</p>
    </section>
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
      </nav>
      <main><Routes><Route path="*" element={<Dashboard />} /></Routes></main>
    </div>
  );
}

function AuthenticatedRoutes() {
  const auth = useAuth();
  if (auth.status === "loading") return <p role="status">세션을 확인하고 있습니다.</p>;
  if (auth.status === "anonymous") {
    return (
      <Routes>
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
