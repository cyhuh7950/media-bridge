export function ConnectionsPage() {
  return (
    <section aria-labelledby="connections-title" className="dependency-page">
      <p className="dependency-badge">DEPENDENCY_NOT_READY</p>
      <h1 id="connections-title">Connections</h1>
      <p>P3 Gateway의 connection API와 저장·시험 계약이 검증된 뒤 P2b에서 활성화됩니다.</p>
      <p>현재 발급되는 client credential은 접근 수단일 뿐 접속 상태를 증명하지 않습니다.</p>
      <div className="dependency-placeholder" aria-label="비활성 기능">
        <strong>현재 사용할 수 없음</strong>
        <span>연결 저장, 시험, 마지막 정상 시각, 폐기는 아직 제공되지 않습니다.</span>
      </div>
    </section>
  );
}
