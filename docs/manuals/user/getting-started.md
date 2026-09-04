# Media Bridge 처음 사용하기

일반 사용자는 Python, Docker, PostgreSQL 또는 `.deb` 명령을 입력하지 않습니다.

## 1. 설치

```bash
npm install -g @cyhuh/media-bridge
```

현재 npm registry 공개와 플랫폼별 runtime artifact 배포는 release 검증 대상입니다.
실제 외부 설치 검증은 [외부 설치 테스트](external-test.md)의 증거 양식을 사용합니다.

## 2. 최초 설정

```bash
mb init
```

첫 질문에는 OpenCodex에 설정할 Media Bridge provider 주소를 입력합니다. 기본값은
`http://127.0.0.1:8765/v1`입니다. 이어서 Media Bridge 포트, Solar 모델·endpoint·Secret
참조명, Upstage Document Parse endpoint·Secret 참조명과 변환 정책을 입력합니다.
Secret 원문은 입력하거나 저장하지 않습니다.

기본 Secret 참조명이 `SOLAR_API_KEY`라면 같은 터미널 환경에 Upstage API key를 설정한 뒤
시작합니다.

```bash
export SOLAR_API_KEY='발급받은-key'
mb start
```

## 3. 시작

```bash
mb start
mb health --json
mb gui
```

관리된 runtime artifact가 준비되지 않은 경우 `mb start`는 fail-closed로 중단됩니다.
이때 Python, Docker 또는 `.deb`를 직접 설치하지 말고 해당 플랫폼용 npm runtime release가
준비되었는지 확인합니다.
지원 플랫폼에서는 첫 시작에 필요한 내부 runtime 설정과 secret 파일을 자동 생성하므로
사용자가 별도 Python 환경이나 runtime 설정 파일을 만들지 않습니다.

npm 설치는 단일 사용자용 `personal` 모드입니다. PostgreSQL·서명 snapshot·Control Plane을
사용하는 `managed` 모드는 서버 운영용으로 그대로 유지되며 npm 기본 실행과 섞이지 않습니다.

## 4. 중지·재시작·제거

```bash
mb stop
mb service restart
mb service uninstall
mb uninstall
npm uninstall -g @cyhuh/media-bridge
```

`mb service uninstall`은 service marker만 제거합니다. `mb uninstall`은 관리 runtime까지 제거하고
설정은 기본적으로 보존하며, 마지막 npm 명령이 전역 CLI 패키지를 제거합니다. 설정도 삭제하려면
`mb uninstall --delete-config`를 사용합니다.

전체 명령과 설정 항목은 [npm CLI 사용법](npm-cli.md)을 참고합니다.
