# OpenCodex 연결

## 연결 주소

Media Bridge를 시작한 뒤 Web 설정 화면의 OpenCodex endpoint에 다음 주소를 입력합니다.

`http://127.0.0.1:8766/v1`

OpenCodex 설정에서는 Responses API와 Media Bridge credential reference를 선택합니다. API key 원문은
입력하지 않습니다. 기존 설정을 덮어쓰지 말고 별도 profile에서 먼저 연결을 확인합니다.

## 연결 확인

1. Web 설정을 저장합니다.
2. OpenCodex에서 text-only 요청을 보냅니다.
3. 정상 응답을 확인합니다.
4. 화면 캡처 요청을 보내 이미지 원문이 전달되지 않고 설명 텍스트로 처리되는지 확인합니다.

인식 결과가 부족하면 요청은 정상 안내 응답으로 끝나며 Solar 호출은 0회입니다.

## 연결 해제

OpenCodex profile에서 Media Bridge endpoint를 제거하거나 이전 endpoint로 되돌립니다. Media Bridge 자체를
중지하려면 Linux 설치 매뉴얼의 중지 절차를 사용합니다.
