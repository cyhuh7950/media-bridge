import type { Role } from "../api/contracts";

export interface OperationsProps {
  role: Role;
  csrfToken: string | null;
}

export function records(value: unknown): Array<Record<string, unknown>> {
  if (!Array.isArray(value)) throw new Error("invalid response");
  return value.filter(
    (item): item is Record<string, unknown> => typeof item === "object" && item !== null,
  );
}

export function textField(record: Record<string, unknown>, key: string): string {
  const value = record[key];
  return typeof value === "string" ? value : "—";
}

export function numberField(record: Record<string, unknown>, key: string): number | null {
  const value = record[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function booleanField(record: Record<string, unknown>, key: string): boolean | null {
  const value = record[key];
  return typeof value === "boolean" ? value : null;
}

export function safeItemPath(root: string, identifier: string, suffix = ""): string {
  if (!/^[A-Za-z0-9._-]+$/.test(identifier)) throw new Error("invalid identifier");
  return `/${root}/${encodeURIComponent(identifier)}${suffix}`;
}
