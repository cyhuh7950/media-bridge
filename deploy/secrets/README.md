# Docker Secret 운영 경계

이 디렉터리에는 Secret 값 파일을 커밋하지 않는다. 최초 배포에서 `deploy/scripts/secret_bootstrap.py`를
root 권한으로 실행해 필요한 시스템 Secret을 생성한다. 이 스크립트는 `media-bridge_database` 볼륨이
없는 초기화 상태에서만 새 값을 만들며, 기존 Secret은 검증 후 그대로 보존한다. 기존 DB 볼륨과 Secret이
맞지 않거나 Secret 세트가 불완전하면 새 값을 만들지 않고 중단한다.

rootful standalone Compose의 file-backed Secret은 host owner/mode를 그대로 유지한다. DB 암호 파일은
컨테이너 UID `999`, 다른 Secret은 UID `10001`, 모두 mode `0400`으로 저장한다. 파일명은 `.secret` 또는
`.pem`을 사용하며 값 파일은 Git과 Docker build context에서 제외된다.

Provider API key, PostgreSQL password, credential pepper, receipt HMAC key와 snapshot
private key는 이미지·설정·로그·snapshot·backup에 포함하지 않는다. 교체 시 새 파일을
원자적으로 배치하고 영향을 받는 서비스만 재시작한 뒤 이전 파일을 제거한다.

`control_security_pepper`와 `gateway_auth_pepper`는 credential digest 발급·검증 계약의
양 끝이므로 같은 Secret 원문을 가리켜야 한다. 두 서비스에는 서로 다른 mount 이름으로
읽기 전용 제공되며, 나머지 서비스별 Secret은 공유하지 않는다. pepper rotation은 새
credential 발급과 signed snapshot 발행을 포함해 원자적으로 수행한다.
