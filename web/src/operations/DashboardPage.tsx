import { useEffect, useState } from "react";

import { adminRequest } from "../api/client";
import { numberField, records, textField } from "./operationTypes";

interface DashboardState {
  health: string;
  providers: number;
  models: number;
  policies: number;
  snapshotVersion: number | null;
  latestEvent: string;
}

export function DashboardPage() {
  const [state, setState] = useState<DashboardState | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    void Promise.all([
      adminRequest<Record<string, unknown>>("/health"),
      adminRequest<unknown>("/providers"),
      adminRequest<unknown>("/models"),
      adminRequest<unknown>("/policies"),
      adminRequest<unknown>("/snapshots"),
      adminRequest<unknown>("/events"),
    ]).then(
      ([health, providersValue, modelsValue, policiesValue, snapshotsValue, eventsValue]) => {
        const snapshots = records(snapshotsValue);
        const events = records(eventsValue);
        const latestSnapshot = snapshots.at(0);
        const latestEvent = events.at(0);
        if (!active) return;
        setState({
          health: textField(health, "status"),
          providers: records(providersValue).length,
          models: records(modelsValue).length,
          policies: records(policiesValue).length,
          snapshotVersion: latestSnapshot ? numberField(latestSnapshot, "version") : null,
          latestEvent: latestEvent ? textField(latestEvent, "event_type") : "기록 없음",
        });
      },
      () => {
        if (active) setFailed(true);
      },
    );
    return () => {
      active = false;
    };
  }, []);

  if (failed) return <p role="alert">Dashboard 상태를 불러올 수 없습니다.</p>;
  if (state === null) return <p role="status">Dashboard 상태를 불러오고 있습니다.</p>;
  return (
    <section aria-labelledby="dashboard-title">
      <p className="eyebrow">Control Plane</p>
      <h1 id="dashboard-title">Dashboard</h1>
      <dl className="metric-grid">
        <div><dt>Control Plane</dt><dd>{state.health}</dd></div>
        <div><dt>Providers</dt><dd>{state.providers}</dd></div>
        <div><dt>Models</dt><dd>{state.models}</dd></div>
        <div><dt>Policies</dt><dd>{state.policies}</dd></div>
        <div><dt>활성 snapshot</dt><dd>{state.snapshotVersion ?? "없음"}</dd></div>
        <div><dt>최근 event</dt><dd>{state.latestEvent}</dd></div>
      </dl>
    </section>
  );
}
