import { useEffect, useState } from "react";

import { adminRequest } from "../api/client";

export function SystemCheckStep({ onReady }: { onReady: () => void }) {
  const [status, setStatus] = useState<"checking" | "ready" | "failed">("checking");

  useEffect(() => {
    let active = true;
    void adminRequest<{ status: string }>("/health")
      .then((response) => {
        if (active) setStatus(response.status === "ok" ? "ready" : "failed");
      })
      .catch(() => {
        if (active) setStatus("failed");
      });
    return () => { active = false; };
  }, []);

  return (
    <section className="setup-card" aria-labelledby="system-check-title">
      <p className="step-label">1 · 시스템 확인</p>
      <h1 id="system-check-title">Control Plane 연결 확인</h1>
      {status === "checking" ? <p role="status">상태를 확인하고 있습니다.</p> : null}
      {status === "failed" ? <p role="alert">Control Plane 상태를 확인할 수 없습니다.</p> : null}
      {status === "ready" ? (
        <>
          <p role="status">실제 `/admin/v1/health` 응답이 정상입니다.</p>
          <button type="button" onClick={onReady}>관리자 설정 계속</button>
        </>
      ) : null}
    </section>
  );
}
