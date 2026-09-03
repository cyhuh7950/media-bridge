# Media Bridge npm CLI 사용법

## 설치

```bash
npm install -g @cyhuh/media-bridge
```

현재 패키지 공개와 플랫폼별 runtime artifact 배포는 별도 release 검증 대상입니다.

## 최초 설정

```bash
mb init
```

질문에 OpenCodex 주소, Media Bridge 포트, Solar 모델·endpoint·Secret 참조,
OCR/Vision 변환 기본값과 변환 실패 시 Solar 전송 차단 정책을 입력합니다.
Secret 원문과 이미지 원문은 입력하거나 저장하지 않습니다.

## 실행과 상태

```bash
mb start
mb start --port 8765
mb status
mb health --json
mb gui
```

첫 `mb start`는 현재 OS·아키텍처에 맞는 관리 runtime을 자동으로 선택하고 다운로드한 뒤
SHA-256과 실행 파일을 검증합니다. URL, checksum 또는 Python 경로를 사용자가 입력하지 않습니다.
검증이 끝나기 전에는 기존 runtime을 교체하지 않으며, 실패하면 시작을 중단합니다.

관리된 runtime artifact가 공개되지 않은 플랫폼에서는 Python이나 `.deb`를 직접 설치하지 말고
설치 불가 사유를 확인합니다.

## lifecycle

```bash
mb stop
mb service install
mb service start
mb service stop
mb service restart
mb service uninstall
mb update
```

`service`는 현재 CLI-managed lifecycle입니다. systemd 또는 Windows 서비스 등록은
별도 운영 배포 범위입니다.

## 제거

```bash
mb uninstall
npm uninstall -g @cyhuh/media-bridge
```

`mb uninstall`은 Media Bridge 프로세스를 중지하고 service marker, PID state와 관리 runtime을
제거합니다. 터미널에서 직접 실행하면 설정 삭제 여부를 물으며 기본값은 보존입니다.

자동화나 스크립트에서는 다음 중 하나를 명시합니다.

```bash
mb uninstall --keep-config
mb uninstall --delete-config
```

플래그가 없는 비대화형 실행은 설정을 보존합니다. 두 플래그를 동시에 사용할 수 없습니다.
설정 삭제를 선택해도 Media Bridge가 소유하지 않은 파일은 삭제하지 않습니다. 마지막
`npm uninstall -g` 명령은 `mb`와 `media-bridge` 전역 CLI를 제거합니다.
