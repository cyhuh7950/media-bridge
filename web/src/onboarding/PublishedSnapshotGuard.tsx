import { useEffect, useState } from "react";
import { Navigate, Outlet } from "react-router-dom";

import { adminRequest } from "../api/client";

export function PublishedSnapshotGuard() {
  const [state, setState] = useState<"loading" | "ready" | "setup" | "error">("loading");
  useEffect(() => {
    let active = true;
    void adminRequest<unknown[]>("/snapshots")
      .then((snapshots) => {
        if (active) setState(Array.isArray(snapshots) && snapshots.length > 0 ? "ready" : "setup");
      })
      .catch(() => { if (active) setState("error"); });
    return () => { active = false; };
  }, []);
  if (state === "loading") return <p role="status">활성 snapshot을 확인하고 있습니다.</p>;
  if (state === "setup") return <Navigate to="/setup" replace />;
  if (state === "error") return <p role="alert">활성 snapshot 상태를 확인할 수 없습니다.</p>;
  return <Outlet />;
}
