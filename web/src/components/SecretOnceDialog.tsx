export function SecretOnceDialog({
  title,
  values,
  closeLabel,
  onClose,
}: {
  title: string;
  values: readonly string[];
  closeLabel: string;
  onClose: () => void;
}) {
  return (
    <section className="dialog-backdrop" role="dialog" aria-modal="true" aria-labelledby="secret-title">
      <div className="dialog-card">
        <h2 id="secret-title">{title}</h2>
        <p>이 값은 다시 표시되지 않습니다. 안전한 Secret 저장소에 보관하세요.</p>
        <pre className="secret-once">{values.join("\n")}</pre>
        <button type="button" onClick={onClose}>{closeLabel}</button>
      </div>
    </section>
  );
}
