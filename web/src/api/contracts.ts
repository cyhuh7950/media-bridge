export type Role = "admin" | "operator" | "viewer";

export interface Principal {
  username: string;
  role: Role;
}

export interface LoginResponse extends Principal {
  csrf_token: string;
}

export interface TotpEnrollmentResponse {
  user_id: string;
  secret: string;
  provisioning_uri: string;
}

export function isTotpEnrollmentResponse(value: unknown): value is TotpEnrollmentResponse {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return typeof candidate.user_id === "string" && typeof candidate.secret === "string" && typeof candidate.provisioning_uri === "string";
}

export function isRole(value: unknown): value is Role {
  return value === "admin" || value === "operator" || value === "viewer";
}

export function isPrincipal(value: unknown): value is Principal {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return typeof candidate.username === "string" && isRole(candidate.role);
}

export function isLoginResponse(value: unknown): value is LoginResponse {
  if (!isPrincipal(value)) return false;
  return (
    "csrf_token" in value &&
    typeof (value as Record<string, unknown>).csrf_token === "string"
  );
}
