# Media Bridge 문제 해결

- Data가 ready가 아니면 첫 signed snapshot, signature key ID, snapshot volume UID를 확인한다.
- `credential_invalid`이면 credential scope/expiry/revoke와 Control/Data pepper 참조 일치를 확인한다.
- `https_required`/`origin_rejected`이면 proxy scheme, Host, Origin allowlist를 확인한다.
- capability unknown/stale, OCR/Vision/sanitizer/cleanup 실패는 정상적인 fail-closed 차단이다.
- 실패 뒤 원본 media를 Non-Vision 모델에 직접 보내 우회하지 않는다.

오류 보고에는 safe error code와 request ID만 사용하고 Secret·media·OCR 본문을 첨부하지 않는다.
