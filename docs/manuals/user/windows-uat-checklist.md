# Windows npm CLI 외부 테스트 체크리스트

## 설치 전

- [ ] 기존 Media Bridge가 실행 중이지 않다.
- [ ] Node.js 18 이상과 npm이 준비되어 있다.
- [ ] npm registry의 `@cyhuh/media-bridge` 공개 여부를 확인했다.

## 설치·최초 설정

- [ ] `npm install -g @cyhuh/media-bridge`가 성공했다.
- [ ] `mb init`이 완료됐다.
- [ ] OpenCodex·Solar endpoint와 정확한 model ID를 설정했다.
- [ ] credential 원문을 입력하지 않았다.
- [ ] `mb status`와 `mb health --json`을 실행했다.

## 핵심 사용

- [ ] `mb start`가 성공했다.
- [ ] `mb ready --wait --timeout 30`이 성공했다.
- [ ] `mb gui`가 설정 주소를 출력한다.

## 복구·제거

- [ ] `mb service restart` 후 상태가 유지된다.
- [ ] `mb stop` 후 process와 port가 정리된다.
- [ ] `mb service uninstall` 후 service marker가 사라진다.
- [ ] `npm uninstall -g @cyhuh/media-bridge`가 성공한다.

## 외부 종속 검증

- [ ] 실제 OpenCodex 연결을 확인했다.
- [ ] 실제 Solar/OCR/Vision provider 호출을 확인했다.
- [ ] 위 항목은 CLI 계약·fixture 테스트와 별도로 기록했다.
