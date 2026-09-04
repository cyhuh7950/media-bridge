# OpenCodex 연결

> 이 문서는 npm CLI의 설정·lifecycle과 실제 OpenCodex 연동을 구분합니다. 현재
> Media Bridge CLI에는 별도 Web 설정 화면이나 `8766/status` 서비스가 없습니다.

## 연결 주소

`mb init`의 첫 주소는 Media Bridge가 OpenCodex를 호출할 주소가 아닙니다. OpenCodex의
provider 설정에 넣을 Media Bridge 주소입니다.

`http://127.0.0.1:8765/v1`

OpenCodex 설정에서는 이 값을 provider base URL로 지정하고 wire API는 `responses`를 선택합니다.
npm `personal` 모드는 loopback 전용이므로 별도 Media Bridge bearer key는 사용하지 않습니다.
기존 OpenCodex 설정을 덮어쓰지 말고 별도 profile에서 먼저 연결을 확인합니다.

## 연결 확인

1. `mb init`을 실행합니다.
2. `mb start`와 `mb health --json`을 실행합니다.
3. OpenCodex에서 text-only 요청을 보냅니다.
4. 실제 media 요청은 provider·비용·downstream 호출 증거를 별도로 기록합니다.

1차 지원 범위는 text 및 image 입력입니다. 이미지는 Upstage Document Parse가 텍스트를 추출하며,
원본 이미지가 제거된 뒤 Solar-4가 응답합니다. OCR이나 정규화가 실패하면 요청은 차단되고
Solar 호출은 0회입니다. tool/file/shell 변환과 토큰 단위 실시간 streaming은 아직 지원 완료로
간주하지 않습니다.

## 연결 해제

OpenCodex profile에서 Media Bridge endpoint를 제거하거나 이전 endpoint로 되돌립니다. Media Bridge 자체를
중지하려면 Linux 설치 매뉴얼의 중지 절차를 사용합니다.
