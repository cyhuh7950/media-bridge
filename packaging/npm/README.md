# Media Bridge CLI

이 패키지는 Media Bridge의 설치 후 실행·상태 확인·설정 진입점을 제공합니다.

```bash
npm install -g @bitkyc08/media-bridge
mb init
mb start
```

현재 실행기는 관리된 Media Bridge runtime을 사용합니다. 지원 플랫폼용 runtime
artifact가 없는 경우에는 사용자에게 Python, Docker 또는 `.deb` 설치를 요구하지 않고
설치 불가 사유를 표시합니다.

공개된 `0.1.3` 패키지는 Linux x64에서 관리 runtime을 자동으로 다운로드하고 SHA-256을
검증합니다. manifest에 공개 산출물이 없는 플랫폼은 fail-closed로 중단합니다.

## 제거

```bash
mb uninstall
npm uninstall -g @bitkyc08/media-bridge
```

첫 명령은 관리 runtime과 service 상태를 제거하고 설정은 기본적으로 보존합니다. 설정까지 삭제하려면
대화형 질문에서 동의하거나 `mb uninstall --delete-config`를 사용합니다. 비대화형 기본값과
`--keep-config`는 설정을 보존합니다. 두 번째 명령은 전역 CLI 패키지를 제거합니다.
