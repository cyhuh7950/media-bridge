# Windows UAT checklist — 신산님 인계용

상태: `HANDOFF_PENDING`; 이 checklist는 Agent가 Windows PASS를 주장하기 위한 문서가 아니다.
Agent의 Linux/WSL evidence와 synthetic provider 결과는 Windows UAT를 대체하지 않는다.

## 격리 준비

- [ ] 별도 Windows 사용자 또는 격리 Codex Desktop profile을 사용한다.
- [ ] 기존 `CODEX_HOME`, config, profile, thread history의 read-only hash를 기록한다.
- [ ] 기존 OpenCodex/OmniRoute 설정을 백업하고 Media Bridge 소유 block만 변경 대상으로 표시한다.
- [ ] 실제 Solar를 사용할 경우 호출 상한을 text 1건, screenshot 1건, invalid 1건으로 고정하고 concurrency 1을 유지한다.

## 설치·최초 설정

- [ ] 서명과 checksum을 확인한 signed MSI를 설치한다. unsigned artifact는 `QA/UNSIGNED`로 표시한다.
- [ ] Docker/PostgreSQL/Redis/Python/Node 수동 설치 없이 첫 실행 UI가 열린다.
- [ ] Web UI가 loopback에만 바인딩된다.
- [ ] OpenCodex detection, Solar endpoint/model ID, credential reference, RPM/TPM 기본값을 확인한다.
- [ ] 설정 apply 전에 preview/backup/hash가 표시되고, duplicate apply는 무변경이다.

## 핵심 사용

- [ ] 텍스트-only 코딩 요청이 변환 없이 Solar에 전달된다.
- [ ] IDE 코드 오류 화면 캡처를 첨부한다.
- [ ] 터미널 stack trace 캡처를 첨부한다.
- [ ] 브라우저 UI/console 오류 캡처를 첨부한다.
- [ ] Windows 오류창 또는 설정 화면 캡처를 첨부한다.
- [ ] 정상 screenshot은 구조화된 화면 맥락·오류·파일/라인·UI 관계·확실/불확실 관측으로 변환된다.
- [ ] Solar 입력에는 원본 image/data URI가 없고 `converted=true`, `original_image_removed=true`와 provenance가 확인된다.

## 실패·보안

- [ ] 흐림/빈 화면/작은 글씨/잘림/모순/timeout/민감정보 마스킹 후 핵심 부족 입력은 정상 안내를 표시한다.
- [ ] 위 실패 입력의 Solar/downstream 호출은 0회다.
- [ ] 실패 후 다음 text-only 요청과 재첨부 요청이 정상 처리된다.
- [ ] Secret·API key·개인정보·원본 screenshot·OCR 본문이 로그/설정/Git에 남지 않는다.
- [ ] 중복 요청·stale image 재사용·부분 파일 변경이 없다.

## 재시작·변경·제거

- [ ] Codex Desktop, OpenCodex, Media Bridge를 재시작한 뒤 설정이 유지된다.
- [ ] 설정 변경 전후 backup/hash와 marker 소유 범위를 확인한다.
- [ ] 의도적 rollback 후 원본 byte/hash가 복원된다.
- [ ] Media Bridge 중지/제거 후 process/listener/cache/temp가 0이다.
- [ ] 원래 Codex Desktop/OpenCodex 설정 hash가 복원되고 다른 작업은 영향을 받지 않는다.

## 증거 제출

기록할 항목: Windows·MSI·Codex Desktop·OpenCodex 버전, 각 단계 결과(PASS/FAIL/UNVERIFIED),
redacted screenshot/provenance, provider 호출 횟수, config hash 전후, rollback 결과, cleanup
잔류 0. Secret 원문과 민감한 화면 내용은 제출하지 않는다.
