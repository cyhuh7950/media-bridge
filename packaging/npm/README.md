# Media Bridge CLI

이 패키지는 Media Bridge의 설치 후 실행·상태 확인·설정 진입점을 제공합니다.

```bash
npm install -g @cyhuh/media-bridge
mb init
mb start
```

`mb gui`는 데스크톱에서 로컬 설정·시험 화면을 열고, 화면을 열 수 없는 서버에서는 접속 주소를
표시합니다. 화면에서 코딩 에이전트, OpenAI 호환 Non-Vision LLM, Upstage Document Parse와
API Key를 설정하고 LLM·OCR·전체 pipeline을 각각 시험할 수 있습니다. API Key는 일반 설정과
분리되며 화면에 다시 표시되지 않습니다. 포트 변경을 제외한 Provider 설정은 실행 중 다시
로드됩니다.

npm 패키지는 단일 사용자용 `personal` 모드로 실행됩니다. OpenCodex의 Responses 요청을
Media Bridge가 받고, 이미지에서는 Upstage Document Parse로 텍스트를 추출한 뒤 원본 이미지를
제거하여 Solar-4에 전달합니다. 지원 플랫폼용 runtime
artifact가 없는 경우에는 사용자에게 Python, Docker 또는 `.deb` 설치를 요구하지 않고
설치 불가 사유를 표시합니다.

`0.1.6`부터 Windows x64, Linux x64와 Linux ARM64에서 관리 runtime을 자동으로 다운로드하고
SHA-256을 검증합니다. manifest에 공개 산출물이 없는 플랫폼은 fail-closed로 중단합니다.

첫 시작 시 runtime 구동에 필요한 model registry, asset 디렉터리와 내부 인증 secret을
`~/.media-bridge` 아래에 자동 생성합니다. Secret 원문은 `config.json`에 저장하지 않습니다.

기존 자동화는 `mb init`에서 지정한 환경변수 이름(기본 `SOLAR_API_KEY`)을 계속 사용할 수 있고,
일반 사용자는 설정 화면에서 API Key를 입력할 수 있습니다. OpenCodex provider의 base URL은 기본
`http://127.0.0.1:8642/v1`, wire API는 `responses`입니다. PostgreSQL과 서명 snapshot을
사용하는 다중 사용자 `managed` 모드는 기존 서버 배포 entrypoint로 별도 유지됩니다.

## 제거

```bash
mb uninstall
npm uninstall -g @cyhuh/media-bridge
```

첫 명령은 관리 runtime과 service 상태를 제거하고 설정은 기본적으로 보존합니다. 설정까지 삭제하려면
대화형 질문에서 동의하거나 `mb uninstall --delete-config`를 사용합니다. 비대화형 기본값과
`--keep-config`는 설정과 내부 runtime 설정을 보존합니다. `--delete-config`는 CLI가 생성한 내부
runtime 설정도 제거하지만 asset과 비소유 파일은 보존합니다. 두 번째 명령은 전역 CLI 패키지를 제거합니다.
