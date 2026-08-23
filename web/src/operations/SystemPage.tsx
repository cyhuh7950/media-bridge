import { useEffect, useState } from "react";

import { adminRequest } from "../api/client";
import { textField } from "./operationTypes";

export function SystemPage() {
  const [health, setHealth] = useState<Record<string, unknown> | null>(null);
  const [principal, setPrincipal] = useState<Record<string, unknown> | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let active = true;
    void Promise.all([
      adminRequest<Record<string, unknown>>("/health"),
      adminRequest<Record<string, unknown>>("/me"),
    ]).then(
      ([healthValue, principalValue]) => {
        if (!active) return;
        setHealth(healthValue);
        setPrincipal(principalValue);
      },
      () => { if (active) setFailed(true); },
    );
    return () => { active = false; };
  }, []);
  if (failed) return <p role="alert">System 상태를 불러올 수 없습니다.</p>;
  if (health === null || principal === null) return <p role="status">System 상태를 불러오고 있습니다.</p>;
  return <section aria-labelledby="system-title"><h1 id="system-title">System</h1><dl className="summary-list"><div><dt>Control Plane</dt><dd>{textField(health, "status")}</dd></div><div><dt>사용자</dt><dd>{textField(principal, "username")}</dd></div><div><dt>역할</dt><dd>{textField(principal, "role")}</dd></div></dl></section>;
}
