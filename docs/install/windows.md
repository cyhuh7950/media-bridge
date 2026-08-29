# Windows 설치 안내

이 문서는 개인용 Media Bridge Windows 설치 경계를 정의한다. 공식 배포물은 신뢰 가능한
Authenticode 인증서와 RFC3161 timestamp가 있는 WiX per-user MSI여야 한다. 서명이 없는
내부 산출물은 `QA/UNSIGNED`로만 취급하며 일반 사용자 설치나 제품 완료 증거로 승격하지 않는다.

## 설치 전 확인

- 기존 Codex Desktop/OpenCodex 설정과 profile의 hash를 보존한다.
- Media Bridge가 사용할 사용자 profile과 loopback 포트를 확인한다.
- API key 원문을 파일·명령행·로그에 넣지 않고 환경변수 또는 OS credential reference만 준비한다.
- Docker, PostgreSQL, Redis, Python, Node를 별도로 설치하지 않는다.

## 설치와 첫 실행

서명된 release MSI를 받으면 서명·checksum·출처를 확인한 뒤 per-user 설치를 실행한다. 설치
후 Media Bridge Web UI가 `127.0.0.1`에서 열리고, 첫 실행 화면에서 OpenCodex 감지, Solar
model ID/endpoint, credential reference와 안전한 기본 rate(2,000 RPM / 750,000 TPM)를
확인한다. 설정 저장 전 preview와 backup/hash가 표시되어야 한다.

## QA/UNSIGNED 경계

unsigned MSI 또는 압축된 실행 파일은 자동 설치·제거와 설정 rollback 시험에만 사용한다.
현재 저장소에는 Windows MSI build/signing 및 실제 Windows UAT 증거가 없다. 이 문서는 신산님
UAT 인계 후 `docs/manuals/user/windows-uat-checklist.md`의 절차를 그대로 수행한다.

## 제거와 복구

제거 전 보존할 local state를 선택한다. Media Bridge가 소유한 marker block만 rollback하고,
소유하지 않은 Codex Desktop/OpenCodex 설정은 삭제하지 않는다. 설치 실패 또는 중단 시 이전
binary/config snapshot으로 복구하고 Web UI·process·loopback listener가 남지 않는지 확인한다.
