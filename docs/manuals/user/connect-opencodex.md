# OpenCodex 연결

> 이 문서는 npm CLI의 설정·lifecycle과 실제 OpenCodex 연동을 구분합니다. 현재
> Media Bridge CLI에는 별도 Web 설정 화면이나 `8766/status` 서비스가 없습니다.

## 연결 주소

`mb init`에서 OpenCodex endpoint를 설정합니다. 기본 Media Bridge 주소는 다음과 같습니다.

`http://127.0.0.1:8765`

OpenCodex 설정에서는 Responses API와 Media Bridge credential reference를 선택합니다. API key 원문은
입력하지 않습니다. 기존 설정을 덮어쓰지 말고 별도 profile에서 먼저 연결을 확인합니다.

## 연결 확인

1. `mb init`을 실행합니다.
2. `mb start`와 `mb health --json`을 실행합니다.
3. OpenCodex에서 text-only 요청을 보냅니다.
4. 실제 media 요청은 provider·비용·downstream 호출 증거를 별도로 기록합니다.

인식 결과가 부족하면 요청은 정상 안내 응답으로 끝나며 Solar 호출은 0회입니다.

## 연결 해제

OpenCodex profile에서 Media Bridge endpoint를 제거하거나 이전 endpoint로 되돌립니다. Media Bridge 자체를
중지하려면 Linux 설치 매뉴얼의 중지 절차를 사용합니다.
