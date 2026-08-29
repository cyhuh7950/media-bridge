# Media Bridge 문제 해결

## Web이 열리지 않음

```bash
systemctl --user restart media-bridge-web.service
systemctl --user --no-pager status media-bridge-web.service
```

주소는 `http://127.0.0.1:8765/`인지 확인합니다.

## Data 상태가 정상적이지 않음

```bash
systemctl --user restart media-bridge-data.service
systemctl --user --no-pager status media-bridge-data.service
curl http://127.0.0.1:8766/status
```

최초 설정이 저장되지 않았거나 유효한 snapshot이 없으면 요청이 차단될 수 있습니다.

## 설정 저장 실패

endpoint에 사용자명·비밀번호·query를 넣지 않습니다. model ID는 실제 제공자가 요구하는 정확한 값을
입력하고 RPM·TPM은 양의 정수로 입력합니다.

## 화면 인식 차단

화면을 확대하고 오류 영역만 다시 캡처합니다. 작은 글씨, 흐림, 잘린 오류 문구를 피하고 필요하면
오류 문구를 직접 입력합니다. 인식이 부족한 화면을 Solar로 우회 전달하지 않습니다.

## 로그 확인

```bash
journalctl --user -u media-bridge-web.service -u media-bridge-data.service --since "10 minutes ago" --no-pager
```

로그와 오류 보고에는 key 원문, 화면 원문, OCR 원문을 넣지 않습니다.
