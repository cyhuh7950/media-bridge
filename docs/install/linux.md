# Linux에서 Media Bridge 설치·실행

## 일반 사용자 설치

일반 사용자는 npm 패키지만 설치합니다.

```bash
npm install -g @bitkyc08/media-bridge
mb init
mb start
```

사용자는 Python, Docker, PostgreSQL 또는 `.deb` 명령을 직접 실행하지 않습니다.

## `mb init` 설정

`mb init`에서 OpenCodex 주소, Media Bridge 포트(기본 `8765`), Solar 모델·HTTPS
endpoint·Secret 참조, OCR/Vision 변환 기본값, 변환 실패 시 Solar 전송 차단 정책을 입력합니다.
설정은 `$HOME/.media-bridge/config.json`에 저장되며 Secret 원문은 저장하지 않습니다.

## 명령

```bash
mb init
mb start [--port 8765]
mb stop
mb status
mb health [--json]
mb gui
mb service install
mb service start
mb service stop
mb service restart
mb service uninstall
mb update
```

`mb gui`는 현재 설정된 Web 주소를 표시합니다. `mb health`가 실패하면 Media Bridge가
준비되지 않은 상태입니다. runtime artifact가 없는 경우에는 Python이나 `.deb`를 직접
설치하지 말고 지원 플랫폼 release 준비 여부를 확인합니다.

## 내부 배포·복구용 `.deb`

`.deb`는 일반 사용자 설치 경로가 아니라 내부 배포·복구용 artifact로 유지합니다.
checksum, `dpkg`, service와 운영 설치 검증은 운영자 절차 및 별도 승인 범위입니다.

## 현재 미검증 범위

- npm registry 공개와 실제 원격 `npm install -g`
- Linux 아키텍처별 runtime artifact release
- 실제 OpenCodex 연결과 Solar Provider 호출
- systemd 자동 시작과 다른 PC 브라우저
