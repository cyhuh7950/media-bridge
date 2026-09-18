import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { adminRequest, SafeApiError } from "../api/client";
import {
  isLoginResponse,
  isPrincipal,
  type LoginResponse,
  type Principal,
} from "../api/contracts";

type AuthState =
  | { status: "loading" }
  | { status: "anonymous"; errorCode?: string }
  | { status: "totp_required"; username: string; password: string; errorCode?: string }
  | { status: "totp_enrollment"; username: string; password: string; userId: string; provisioningUri: string; secret: string; errorCode?: string }
  | { status: "authenticated"; principal: Principal; csrfToken: string | null };

interface AuthContextValue {
  state: AuthState;
  login: (username: string, password: string) => Promise<void>;
  verifyTotp: (code: string) => Promise<void>;
  beginTotpEnrollment: () => Promise<void>;
  confirmTotpEnrollment: (code: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ status: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    void adminRequest<Principal>("/me", { signal: controller.signal })
      .then((principal) => {
        if (!isPrincipal(principal)) throw new SafeApiError(502, "invalid_response");
        setState({ status: "authenticated", principal, csrfToken: null });
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        const code = error instanceof SafeApiError ? error.code : "request_failed";
        setState({ status: "anonymous", errorCode: code });
      });
    return () => { controller.abort(); };
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    try {
      const response = await adminRequest<LoginResponse>("/auth/login", {
        method: "POST",
        body: { username, password },
      });
      if (!isLoginResponse(response)) throw new SafeApiError(502, "invalid_response");
      setState({
        status: "authenticated",
        principal: { username: response.username, role: response.role },
        csrfToken: response.csrf_token,
      });
    } catch (error: unknown) {
      const code = error instanceof SafeApiError ? error.code : "request_failed";
      if (code === "totp_required") setState({ status: "totp_required", username, password });
      else setState({ status: "anonymous", errorCode: code });
    }
  }, []);

  const verifyTotp = useCallback(async (code: string) => {
    if (state.status !== "totp_required" && state.status !== "totp_enrollment") return;
    const username = state.username;
    const password = state.password;
    try {
      const response = await adminRequest<LoginResponse>("/auth/totp/login", { method: "POST", body: { username, password, code } });
      if (!isLoginResponse(response)) throw new SafeApiError(502, "invalid_response");
      setState({ status: "authenticated", principal: { username: response.username, role: response.role }, csrfToken: response.csrf_token });
    } catch (error: unknown) {
      setState({ status: "totp_required", username, password, errorCode: error instanceof SafeApiError ? error.code : "request_failed" });
    }
  }, [state]);

  const beginTotpEnrollment = useCallback(async () => {
    if (state.status !== "totp_required") return;
    try {
      const response = await adminRequest<{ user_id: string; secret: string; provisioning_uri: string }>("/auth/totp/enroll", { method: "POST", body: { username: state.username, password: state.password } });
      if (!response || typeof response.user_id !== "string") throw new SafeApiError(502, "invalid_response");
      setState({ status: "totp_enrollment", username: state.username, password: state.password, userId: response.user_id, provisioningUri: response.provisioning_uri, secret: response.secret });
    } catch (error: unknown) {
      setState({ ...state, errorCode: error instanceof SafeApiError ? error.code : "request_failed" });
    }
  }, [state]);

  const confirmTotpEnrollment = useCallback(async (code: string) => {
    if (state.status !== "totp_enrollment") return;
    try {
      await adminRequest("/auth/totp/confirm", { method: "POST", body: { user_id: state.userId, code } });
      setState({ status: "totp_required", username: state.username, password: state.password });
    } catch (error: unknown) {
      setState({ ...state, errorCode: error instanceof SafeApiError ? error.code : "request_failed" });
    }
  }, [state]);

  const logout = useCallback(async () => {
    if (state.status !== "authenticated" || state.csrfToken === null) {
      setState({ status: "anonymous" });
      return;
    }
    try {
      await adminRequest("/auth/logout", {
        method: "POST",
        csrfToken: state.csrfToken,
      });
    } finally {
      setState({ status: "anonymous" });
    }
  }, [state]);

  const value = useMemo(() => ({ state, login, verifyTotp, beginTotpEnrollment, confirmTotpEnrollment, logout }), [state, login, verifyTotp, beginTotpEnrollment, confirmTotpEnrollment, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthState & Pick<AuthContextValue, "login" | "verifyTotp" | "beginTotpEnrollment" | "confirmTotpEnrollment" | "logout"> {
  const context = useContext(AuthContext);
  if (context === null) throw new Error("AuthProvider is required");
  return { ...context.state, login: context.login, logout: context.logout };
}
