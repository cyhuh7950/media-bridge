import { useState, type SyntheticEvent } from "react";

import { adminRequest } from "../api/client";
import { textField, type OperationsProps } from "./operationTypes";
import { useAdminList } from "./useAdminList";

export function ModelsPage({ role, csrfToken }: OperationsProps) {
  const { items, failed, reload } = useAdminList("/models");
  const [modelId, setModelId] = useState("");
  const [evidence, setEvidence] = useState("");
  const [saveFailed, setSaveFailed] = useState(false);
  const writable = role !== "viewer" && csrfToken !== null;

  async function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!writable) return;
    const reviewed = new Date();
    try {
      await adminRequest("/models", {
        method: "POST",
        csrfToken,
        body: {
          model_id: modelId,
          aliases: [],
          input_modalities: ["text"],
          evidence,
          reviewed_at: reviewed.toISOString(),
          expires_at: new Date(reviewed.getTime() + 30 * 24 * 60 * 60 * 1000).toISOString(),
          pdf_passthrough_verified: false,
        },
      });
      setModelId("");
      setEvidence("");
      setSaveFailed(false);
      await reload();
    } catch {
      setSaveFailed(true);
    }
  }

  return (
    <section aria-labelledby="models-title">
      <h1 id="models-title">Models</h1>
      <p>Capability가 확인되지 않거나 만료되면 fail-closed로 처리됩니다.</p>
      {failed ? <p role="alert">Model 목록을 불러올 수 없습니다.</p> : null}
      {items ? <table><thead><tr><th>Model ID</th><th>근거</th><th>만료</th></tr></thead><tbody>{items.map((item) => <tr key={textField(item, "id")}><td>{textField(item, "model_id")}</td><td>{textField(item, "evidence")}</td><td>{textField(item, "expires_at")}</td></tr>)}</tbody></table> : null}
      {writable ? <form className="form-grid compact-form" onSubmit={(event) => { void submit(event); }}><h2>Non-Vision model 추가</h2><label htmlFor="operation-model-id">Model ID</label><input id="operation-model-id" value={modelId} onChange={(event) => { setModelId(event.target.value); }} required /><label htmlFor="operation-model-evidence">Capability 근거</label><textarea id="operation-model-evidence" value={evidence} onChange={(event) => { setEvidence(event.target.value); }} required />{saveFailed ? <p role="alert">Model을 저장할 수 없습니다.</p> : null}<button type="submit">Model 추가</button></form> : <p>viewer는 Model capability를 읽기만 할 수 있습니다.</p>}
    </section>
  );
}
