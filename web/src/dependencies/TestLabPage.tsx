export function TestLabPage() {
  return (
    <section aria-labelledby="test-lab-title" className="dependency-page">
      <p className="dependency-badge">DEPENDENCY_NOT_READY</p>
      <h1 id="test-lab-title">Test Lab</h1>
      <p>P3 Gateway의 asset·preview·responses 시험 계약이 검증된 뒤 P2b에서 활성화됩니다.</p>
      <p>현재 화면은 업로드, preview, OCR 본문 또는 downstream 호출을 만들지 않습니다.</p>
      <div className="dependency-placeholder" aria-label="비활성 기능">
        <strong>현재 사용할 수 없음</strong>
        <span>실제 downstream 호출은 P2b에서도 기본 off이며 명시적 opt-in이 필요합니다.</span>
      </div>
    </section>
  );
}
