import { useState, type SyntheticEvent } from "react";

import { adminRequest } from "../api/client";

export function PolicyStep({ csrfToken, onSaved }: { csrfToken: string; onSaved: () => Promise<void> }) {
  const [name, setName] = useState("default");
  const [failed, setFailed] = useState(false);

  async function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      await adminRequest("/policies", {
        method: "POST",
        csrfToken,
        body: {
          name,
          max_files: 4,
          max_media_bytes: 2_097_152,
          max_pdf_pages: 20,
          allow_url: false,
          allow_base64: true,
          allow_asset: true,
          allow_local_path: false,
          fail_closed: true,
        },
      });
      await onSaved();
    } catch {
      setFailed(true);
    }
  }

  return (
    <section className="setup-card" aria-labelledby="policy-step-title">
      <p className="step-label">5 · Policy</p>
      <h1 id="policy-step-title">Fail-closed 정책 생성</h1>
      <form className="form-grid" onSubmit={(event) => { void submit(event); }}>
        <label htmlFor="policy-name">정책 이름</label>
        <input id="policy-name" value={name} onChange={(event) => { setName(event.target.value); }} required />
        <dl className="summary-list"><div><dt>최대 파일</dt><dd>4</dd></div><div><dt>최대 크기</dt><dd>2 MiB</dd></div><div><dt>Fail closed</dt><dd>항상 적용</dd></div></dl>
        {failed ? <p role="alert">정책을 저장할 수 없습니다.</p> : null}
        <button type="submit">안전 정책 저장</button>
      </form>
    </section>
  );
}
