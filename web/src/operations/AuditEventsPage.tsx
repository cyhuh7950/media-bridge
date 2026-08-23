import { useEffect, useState } from "react";

import { adminRequest } from "../api/client";
import { records, textField } from "./operationTypes";

export function AuditEventsPage() {
  const [audit, setAudit] = useState<Array<Record<string, unknown>> | null>(null);
  const [events, setEvents] = useState<Array<Record<string, unknown>> | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let active = true;
    void Promise.all([adminRequest<unknown>("/audit"), adminRequest<unknown>("/events")]).then(
      ([auditValue, eventValue]) => {
        if (!active) return;
        setAudit(records(auditValue));
        setEvents(records(eventValue));
      },
      () => { if (active) setFailed(true); },
    );
    return () => { active = false; };
  }, []);
  if (failed) return <p role="alert">Audit와 event를 불러올 수 없습니다.</p>;
  if (audit === null || events === null) return <p role="status">Audit와 event를 불러오고 있습니다.</p>;
  return (
    <section aria-labelledby="audit-title"><h1 id="audit-title">Audit &amp; Events</h1>
      <h2>Audit</h2><table><thead><tr><th>Action</th><th>Target</th><th>시각</th></tr></thead><tbody>{audit.map((item, index) => <tr key={`${textField(item, "action")}-${String(index)}`}><td>{textField(item, "action")}</td><td>{textField(item, "target_type")}</td><td>{textField(item, "created_at")}</td></tr>)}</tbody></table>
      <h2>Operational events</h2><table><thead><tr><th>Event</th><th>Severity</th><th>시각</th></tr></thead><tbody>{events.map((item, index) => <tr key={`${textField(item, "event_type")}-${String(index)}`}><td>{textField(item, "event_type")}</td><td>{textField(item, "severity")}</td><td>{textField(item, "created_at")}</td></tr>)}</tbody></table>
    </section>
  );
}
