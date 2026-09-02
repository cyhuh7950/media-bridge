# Media Bridge 처음 사용하기

일반 사용자는 Python, Docker, PostgreSQL 또는 `.deb` 명령을 입력하지 않습니다.

## 1. 설치

```bash
npm install -g @bitkyc08/media-bridge
```

현재 npm registry 공개와 플랫폼별 runtime artifact 배포는 release 검증 대상입니다.
실제 외부 설치 검증은 [외부 설치 테스트](external-test.md)의 증거 양식을 사용합니다.

## 2. 최초 설정

```bash
mb init
```

질문에 OpenCodex 주소, Media Bridge 포트, Solar 모델·endpoint·Secret 참조명,
OCR/Vision 변환 기본값과 변환 실패 시 Solar 전송 차단 정책을 입력합니다.
Secret 원문은 입력하거나 저장하지 않습니다.

## 3. 시작

```bash
mb start
mb health --json
mb gui
```

관리된 runtime artifact가 준비되지 않은 경우 `mb start`는 fail-closed로 중단됩니다.
이때 Python, Docker 또는 `.deb`를 직접 설치하지 말고 해당 플랫폼용 npm runtime release가
준비되었는지 확인합니다.

## 4. 중지·재시작·제거

```bash
mb stop
mb service restart
mb service uninstall
```

전체 명령과 설정 항목은 [npm CLI 사용법](npm-cli.md)을 참고합니다.
