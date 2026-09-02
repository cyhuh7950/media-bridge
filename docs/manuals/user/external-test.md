# Media Bridge 외부 설치 테스트

이 문서는 공개 npm 패키지를 실제 사용자 환경에서 확인할 때 사용합니다.

## 사전 조건

- Node.js 18 이상
- npm registry에서 `@bitkyc08/media-bridge` 조회 가능
- 테스트 중 사용할 포트가 비어 있음
- OpenCodex·Solar credential 원문을 문서나 로그에 기록하지 않음

## 설치와 최초 설정

```bash
npm install -g @bitkyc08/media-bridge
mb init
```

`mb init`에서 OpenCodex 주소, Media Bridge 포트, Solar 모델·endpoint·Secret 참조,
변환 기본값과 실패 시 Solar 전송 차단 정책을 설정합니다.

## 실행 검증

```bash
mb start
mb status --json
mb health --json
mb ready --wait --timeout 30
mb gui
```

runtime artifact가 없거나 checksum 검증에 실패하면 `mb start`가 중단되어야 합니다.
이 경우 테스트를 PASS로 기록하지 말고 runtime release 부족으로 기록합니다.

## 종료와 정리

```bash
mb service restart
mb stop
mb service uninstall
npm uninstall -g @bitkyc08/media-bridge
```

종료 후 process, PID/state 파일, 테스트 포트가 남지 않았는지 확인합니다.

## 증거 기록

다음 항목을 각각 기록합니다.

- npm package version과 registry 설치 결과
- 운영체제·아키텍처
- `mb init`, `start`, `status`, `health`, `ready`, `stop` 결과
- runtime artifact 이름과 SHA-256
- 실제 OpenCodex/Solar 호출 여부
- 실패 원인과 재현 명령

Node 계약 테스트, fixture 테스트, 로컬 `npm pack` 결과만으로 외부 설치 PASS를 선언하지 않습니다.
