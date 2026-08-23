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
  | { status: "authenticated"; principal: Principal; csrfToken: string | null };

interface AuthContextValue {
  state: AuthState;
  login: (username: string, password: string) => Promise<void>;
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
      setState({ status: "anonymous", errorCode: code });
    }
  }, []);

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

  const value = useMemo(() => ({ state, login, logout }), [state, login, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthState & Pick<AuthContextValue, "login" | "logout"> {
  const context = useContext(AuthContext);
  if (context === null) throw new Error("AuthProvider is required");
  return { ...context.state, login: context.login, logout: context.logout };
}
