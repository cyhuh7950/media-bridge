import type { ReactNode } from "react";

import type { Role } from "../api/contracts";
import { useAuth } from "./AuthProvider";

export function RequireRole({
  allow,
  children,
  fallback = <p role="status">권한이 없습니다.</p>,
}: {
  allow: readonly Role[];
  children: ReactNode;
  fallback?: ReactNode;
}) {
  const auth = useAuth();
  if (auth.status !== "authenticated") return null;
  return allow.includes(auth.principal.role) ? children : fallback;
}
