# Media Bridge 처음 사용하기

## 1. 시작

Linux에서는 `docs/install/linux.md`의 설치 절차를 먼저 실행합니다. 설치 후 브라우저에서 다음 주소를 엽니다.

`http://127.0.0.1:8765/`

## 2. 첫 설정

화면의 OpenCodex endpoint, Solar endpoint, 정확한 model ID, credential 환경변수 이름을 입력합니다.
필요한 경우 OCR/Vision endpoint와 model ID도 입력합니다. 기본 rate는 RPM 2000, TPM 750000입니다.
key 원문은 입력하지 않습니다.

저장 후 페이지를 새로고침하고 값이 유지되는지 확인합니다. Data 상태는 다음 주소에서 확인합니다.

`http://127.0.0.1:8766/status`

## 3. 첫 화면 요청

1. OpenCodex에서 코딩 작업을 시작합니다.
2. 오류 밑줄, 파일·라인, 터미널 결과가 보이는 화면을 캡처합니다.
3. 캡처와 수정 요청을 함께 보냅니다.
4. 인식이 충분하면 Media Bridge가 이미지 원문을 제거하고 설명 텍스트를 전달합니다.
5. 인식이 부족하면 Solar 호출 없이 재캡처 안내를 표시합니다.

화면을 확대하고, 오류 영역을 잘라 캡처하며, 필요하면 오류 문구를 직접 붙여 넣습니다.

## 4. 중지와 재시작

```bash
systemctl --user stop media-bridge-web.service media-bridge-data.service
systemctl --user start media-bridge-web.service media-bridge-data.service
```
