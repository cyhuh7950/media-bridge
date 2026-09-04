# Windows에서 Media Bridge 설치·중지·제거

일반 사용자의 Windows 설치 경로는 npm CLI입니다. MSI는 현재 내부 QA·복구용
artifact이며, 이 문서는 MSI에 웹 화면·트레이·시작 메뉴가 있다고 가정하지 않습니다.

## 1. 설치

```powershell
npm install -g @cyhuh/media-bridge
mb init
```

현재 npm registry 공개와 Windows runtime artifact가 준비되지 않았다면 이 명령은
외부 설치 PASS가 아닙니다. 그 경우 Python, Docker 또는 MSI를 사용자 우회 경로로
요구하지 말고 release 준비 상태를 확인합니다.

## 2. 최초 설정

`mb init`에서 OpenCodex 주소, Media Bridge 포트(기본 `8642`), Solar 모델·HTTPS
endpoint·Secret 참조, OCR/Vision 변환 기본값과 변환 실패 시 Solar 전송 차단 정책을
입력합니다. Secret 원문은 저장하지 않습니다.

## 3. 시작·상태·중지

```powershell
mb start
mb status
mb health --json
mb service restart
mb stop
```

`mb gui`는 현재 설정된 주소를 출력합니다. 현재 CLI에는 트레이 아이콘, 시작 메뉴
바로가기 또는 별도 `8766/status` 웹 화면이 없습니다.

## 4. 제거

```powershell
mb service uninstall
npm uninstall -g @cyhuh/media-bridge
```

CLI 설정까지 삭제할 때는 `mb uninstall`을 사용합니다.

MSI를 내부 복구 목적으로 사용하는 경우에도 이 문서의 CLI 사용자 경험과 혼동하지
않으며, MSI의 실제 payload·runtime·실행 경로를 별도 운영 기록으로 남깁니다.
