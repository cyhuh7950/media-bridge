# Docker Secret 운영 경계

이 디렉터리에는 Secret 값 파일을 커밋하지 않는다. 운영자는 배포 호스트에서 mode
`0400` 또는 `0440` 파일을 만들고 Compose의 external secret으로 연결한다. 파일명은
`.secret` 또는 `.pem`을 사용하며 두 패턴은 Git과 Docker build context에서 제외된다.

Provider API key, PostgreSQL password, credential pepper, receipt HMAC key와 snapshot
private key는 이미지·설정·로그·snapshot·backup에 포함하지 않는다. 교체 시 새 파일을
원자적으로 배치하고 영향을 받는 서비스만 재시작한 뒤 이전 파일을 제거한다.

