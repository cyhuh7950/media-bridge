import { useEffect, useState } from "react";
import { Outlet } from "react-router-dom";

import { adminRequest } from "../api/client";
import type { Role } from "../api/contracts";

function AdminPublishedSnapshotGuard() {
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
  // A published snapshot is required for gateway traffic, but not for the
  // administrative console. Operators may configure Providers, Models and
  // Policies before publishing the first snapshot.
  if (state === "setup") return <Outlet />;
  if (state === "error") return <p role="alert">활성 snapshot 상태를 확인할 수 없습니다.</p>;
  return <Outlet />;
}

export function PublishedSnapshotGuard({ role }: { role: Role }) {
  return role === "admin" ? <AdminPublishedSnapshotGuard /> : <Outlet />;
}
