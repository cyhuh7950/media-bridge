# Media Bridge npm CLI 사용법

## 설치

```bash
npm install -g @bitkyc08/media-bridge
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

관리된 runtime artifact가 없는 플랫폼에서는 Python이나 `.deb`를 직접 설치하지 말고
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
