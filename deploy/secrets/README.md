# Docker Secret 운영 경계

이 디렉터리에는 Secret 값 파일을 커밋하지 않는다. 운영자는 배포 호스트에서 값 파일의
owner를 해당 컨테이너 UID(`10001`)로 맞추고 mode `0400`을 적용한 뒤 Compose에
연결한다. rootful standalone Compose의 file-backed Secret은 host owner/mode를 그대로
유지하므로 root 소유 `0400` 파일은 non-root 서비스가 읽지 못한다. 파일명은 `.secret`
또는 `.pem`을 사용하며 두 패턴은 Git과 Docker build context에서 제외된다.

Provider API key, PostgreSQL password, credential pepper, receipt HMAC key와 snapshot
private key는 이미지·설정·로그·snapshot·backup에 포함하지 않는다. 교체 시 새 파일을
원자적으로 배치하고 영향을 받는 서비스만 재시작한 뒤 이전 파일을 제거한다.

`control_security_pepper`와 `gateway_auth_pepper`는 credential digest 발급·검증 계약의
양 끝이므로 같은 Secret 원문을 가리켜야 한다. 두 서비스에는 서로 다른 mount 이름으로
읽기 전용 제공되며, 나머지 서비스별 Secret은 공유하지 않는다. pepper rotation은 새
credential 발급과 signed snapshot 발행을 포함해 원자적으로 수행한다.
