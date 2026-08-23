import { useState, type SyntheticEvent } from "react";

import { adminRequest } from "../api/client";
import { booleanField, numberField, textField, type OperationsProps } from "./operationTypes";
import { useAdminList } from "./useAdminList";

export function PoliciesPage({ role, csrfToken }: OperationsProps) {
  const { items, failed, reload } = useAdminList("/policies");
  const [name, setName] = useState("");
  const [saveFailed, setSaveFailed] = useState(false);
  const writable = role !== "viewer" && csrfToken !== null;

  async function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!writable) return;
    try {
      await adminRequest("/policies", {
        method: "POST",
        csrfToken,
        body: { name, max_files: 4, max_media_bytes: 2_097_152, max_pdf_pages: 20, allow_url: false, allow_base64: true, allow_asset: true, allow_local_path: false, fail_closed: true },
      });
      setName("");
      setSaveFailed(false);
      await reload();
    } catch {
      setSaveFailed(true);
    }
  }

  return (
    <section aria-labelledby="policies-title">
      <h1 id="policies-title">Policies</h1>
      <p>Fail-closed와 미디어 입력 경계를 확인합니다.</p>
      {failed ? <p role="alert">Policy 목록을 불러올 수 없습니다.</p> : null}
      {items ? <table><thead><tr><th>이름</th><th>최대 파일</th><th>PDF 페이지</th><th>Fail closed</th></tr></thead><tbody>{items.map((item) => <tr key={textField(item, "id")}><td>{textField(item, "name")}</td><td>{numberField(item, "max_files") ?? "—"}</td><td>{numberField(item, "max_pdf_pages") ?? "—"}</td><td>{booleanField(item, "fail_closed") === true ? "true" : "invalid"}</td></tr>)}</tbody></table> : null}
      {writable ? <form className="form-grid compact-form" onSubmit={(event) => { void submit(event); }}><h2>Fail-closed policy 추가</h2><label htmlFor="operation-policy-name">Policy 이름</label><input id="operation-policy-name" value={name} onChange={(event) => { setName(event.target.value); }} required />{saveFailed ? <p role="alert">Policy를 저장할 수 없습니다.</p> : null}<button type="submit">Policy 추가</button></form> : <p>viewer는 Policy를 읽기만 할 수 있습니다.</p>}
    </section>
  );
}
