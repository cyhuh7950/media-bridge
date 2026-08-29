# Media Bridge 개인용 설정

이 문서는 개인용 Media Bridge의 loopback Web 설정 화면을 설명합니다. 사용자는
Docker, PostgreSQL, Redis, Python 또는 Node를 별도로 설치하거나 `.env`를 조립하지 않습니다.

## 설정 화면 열기

1. Media Bridge를 시작합니다.
2. 자동으로 열린 브라우저에서 `http://127.0.0.1:<표시된 포트>/`를 확인합니다.
3. 화면에 `로컬 전용`이 표시되는지 확인합니다. `127.0.0.1`이 아닌 주소는 사용하지 않습니다.

최초 화면에는 안전한 Solar rate 기본값인 RPM `2000`, TPM `750000`이 표시됩니다.
이 값은 Solar 사용 한도의 설계 입력값이며 실제 provider 호출을 의미하지 않습니다.

## rate 설정 변경

1. `Solar RPM`과 `Solar TPM`에 양의 정수를 입력합니다.
2. `설정 저장`을 선택합니다.
3. `status: saved`가 표시되면 새 설정이 active snapshot에 원자적으로 저장됩니다.
4. 브라우저를 새로 열어 입력값이 유지되는지 확인합니다.

0 이하, 누락, 숫자가 아닌 값은 저장되지 않으며 기존 설정은 유지됩니다.

## 안전한 화면 요청 처리

화면 캡처의 OCR/Vision 결과가 충분하지 않거나 변환·정제·정리가 실패하면 Media Bridge는
Solar로 보내기 전에 요청을 차단합니다. 이때 downstream 호출은 0회이며 원본 이미지와
민감정보를 오류 메시지나 이벤트에 기록하지 않습니다. 화면을 확대해 다시 캡처하거나,
오류 영역만 잘라 다시 첨부하거나, 판독 가능한 오류 문구를 직접 입력하십시오.

## 재시작과 복구

설정 변경 중 문제가 생기면 이전 정상 snapshot을 보존합니다. Media Bridge를 중지한 뒤
다시 시작하면 마지막 정상 설정으로 복구합니다. 설정 파일을 직접 편집하거나 삭제하지
마십시오.

## 설정 확인과 제거

- 화면에서 현재 rate와 Data 상태를 확인합니다.
- 중지할 때는 Media Bridge의 중지 동작을 사용하고, 강제 종료가 필요하면 재시작 후 상태를 확인합니다.
- 제거 전 설정과 이벤트를 보존할지 결정합니다. Media Bridge가 만든 설정 marker만 복원 대상입니다.
- 실제 OpenCodex 사용자 설정과 Secret 원문은 이 문서나 로그에 기록하지 않습니다.

## 현재 검증 경계

이 문서의 Web 화면·rate 저장·잘못된 값 차단은 WSL local process에서 검증되었습니다.
실제 OpenCodex 설치, Solar provider 호출, Linux clean-install, Windows UAT는 별도 단계입니다.
