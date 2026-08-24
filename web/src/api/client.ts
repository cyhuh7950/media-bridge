import { SafeApiError, safeErrorCode } from "./errors";

const ADMIN_ROOTS = new Set([
  "audit",
  "auth",
  "bootstrap",
  "connections",
  "credentials",
  "drafts",
  "events",
  "health",
  "me",
  "models",
  "policies",
  "providers",
  "snapshots",
  "test-lab",
  "users",
]);

export { SafeApiError } from "./errors";

export interface AdminRequestOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  csrfToken?: string;
  bootstrapToken?: string;
  signal?: AbortSignal;
}

function adminUrl(path: string): string {
  if (!path.startsWith("/") || path.startsWith("//") || path.includes("://")) {
    throw new SafeApiError(0, "invalid_admin_path");
  }
  const root = path.slice(1).split("/", 1)[0];
  if (!root || !ADMIN_ROOTS.has(root)) {
    throw new SafeApiError(0, "invalid_admin_path");
  }
  return `/admin/v1${path}`;
}

async function responseBody(response: Response): Promise<unknown> {
  if (response.status === 204) return undefined;
  const contentType = response.headers.get("content-type")?.split(";", 1)[0];
  if (contentType !== "application/json") return undefined;
  try {
    return await response.json();
  } catch {
    return undefined;
  }
}

export async function adminRequest<T = undefined>(
  path: string,
  options: AdminRequestOptions = {},
): Promise<T> {
  const url = adminUrl(path);
  if (options.bootstrapToken && path !== "/bootstrap") {
    throw new SafeApiError(0, "invalid_admin_path");
  }
  const headers: Record<string, string> = { accept: "application/json" };
  let body: string | undefined;
  if (options.body !== undefined) {
    headers["content-type"] = "application/json";
    body = JSON.stringify(options.body);
  }
  if (options.csrfToken) headers["x-csrf-token"] = options.csrfToken;
  if (options.bootstrapToken) headers["x-bootstrap-token"] = options.bootstrapToken;
  const response = await fetch(url, {
    method: options.method ?? "GET",
    credentials: "include",
    headers,
    body,
    signal: options.signal,
  });
  const payload = await responseBody(response);
  if (!response.ok) throw new SafeApiError(response.status, safeErrorCode(payload));
  return payload as T;
}
