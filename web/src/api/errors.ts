const SAFE_CODE = /^[a-z][a-z0-9_]{0,63}$/;

export class SafeApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string) {
    super(code);
    this.name = "SafeApiError";
    this.status = status;
    this.code = SAFE_CODE.test(code) ? code : "request_failed";
  }
}

export function safeErrorCode(value: unknown): string {
  if (typeof value !== "object" || value === null) return "request_failed";
  const envelope = value as { error?: { code?: unknown } };
  const code = envelope.error?.code;
  return typeof code === "string" && SAFE_CODE.test(code) ? code : "request_failed";
}
