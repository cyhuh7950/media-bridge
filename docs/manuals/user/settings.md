# Media Bridge 설정 변경

## CLI 설정

현재 사용자 설정은 Web 화면이 아니라 `mb init`으로 변경합니다. 설정 파일은
`$HOME/.media-bridge/config.json`에 저장되며 Secret 원문은 저장하지 않습니다.

## 변경할 수 있는 값

- OpenCodex endpoint
- Solar endpoint
- Solar model ID
- Solar credential 환경변수 이름 또는 OS credential reference 이름
- OCR/Vision endpoint와 model ID
- 변환 실패 시 Solar 전송 차단 정책

API key 원문은 입력하지 않습니다. 기본 rate는 RPM 2000, TPM 750000입니다.

## 저장

```bash
mb init
mb status
```

잘못된 endpoint, 빈 model ID, 범위를 벗어난 포트는 저장되지 않습니다.

## 변경 후 확인

```bash
mb service restart
mb health --json
```

문제가 생기면 이전 정상 설정 snapshot으로 복구하고, 설정 파일을 직접 삭제하지 않습니다.
