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

`mb init`은 Media Bridge 기본 포트와 1차 OpenCodex/Solar/Document Parse profile을 만듭니다.
API Key와 실제 Provider 연결은 시작 후 Web 설정 화면에서 입력하고 시험할 수 있습니다.

## 3. 시작

```bash
mb start
mb health --json
mb gui
```

`mb gui`에서 코딩 에이전트, Non-Vision LLM, Vision/OCR 엔진, API Key와 변환 정책을 설정합니다.
기본 profile은 OpenCodex, Solar-4, Upstage Document Parse입니다. 다른 OpenAI 호환 Non-Vision
LLM과 Eoul Gateway도 선택할 수 있습니다. 화면을 열 수 없는 headless 서버에서는 표시된 주소를
SSH port forwarding으로 사용자의 브라우저에서 엽니다.

화면에서 `LLM 연결 시험`, `OCR 연결 시험`, `전체 파이프라인 시험`을 차례로 실행합니다. 포트를
바꾼 경우에만 `mb service restart`로 listener를 다시 시작합니다.

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
