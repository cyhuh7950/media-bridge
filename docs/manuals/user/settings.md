# Media Bridge 설정 변경

## 설정 화면

브라우저에서 `http://127.0.0.1:8765/`를 열고 현재 설정을 확인합니다.

## 변경할 수 있는 값

- OpenCodex endpoint
- Solar endpoint
- Solar model ID
- Solar credential 환경변수 이름 또는 OS credential reference 이름
- OCR/Vision endpoint와 model ID
- Solar RPM·TPM

API key 원문은 입력하지 않습니다. 기본 rate는 RPM 2000, TPM 750000입니다.

## 저장

값을 수정하고 `설정 저장`을 누릅니다. 페이지를 새로고침해 값이 유지되는지 확인합니다.
잘못된 endpoint, 빈 model ID, 0 이하의 rate는 저장되지 않습니다.

## 변경 후 확인

```bash
systemctl --user restart media-bridge-web.service media-bridge-data.service
curl --fail http://127.0.0.1:8766/status
```

문제가 생기면 이전 정상 설정 snapshot으로 복구하고, 설정 파일을 직접 삭제하지 않습니다.
