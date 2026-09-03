# Media Bridge 외부 설치 테스트

이 문서는 공개 npm 패키지를 실제 사용자 환경에서 확인할 때 사용합니다.

## 공개 전 runtime artifact 독립 재검증

공개 전 QA에서는 원격 `main`의 정확한 source commit에서
`Build win32-x64 runtime artifact` workflow를 실행합니다. `gh` CLI는 사용하지 않으며 GitHub Actions
화면에서 실행·다운로드합니다. 다운로드한 private workflow artifact에 다음 네 파일이 있어야 합니다.

- `media-bridge-runtime-<version>-win32-x64.tar.gz`
- 동일 이름의 `.sha256`
- `runtime-manifest.json`
- `verification-result.json`

`verification-result.json`의 `sourceCommit`이 시험 대상 commit과 같고, `sha256`이 archive 및 manifest와
일치하며, `platform=win32-x64`, `python=false`, `pythonDirectCall=false`, `forbiddenEntries=0`,
`healthStatus=200`, `managedInstall=true`, `checksumMismatchRejected=true`,
`managedRollbackPreserved=true`인지 확인합니다. workflow가 실패하거나 이 증거가 없으면 실제 artifact E2E는
`PASS`가 아니라 `FAIL` 또는 `NOT RUN`으로 기록합니다. 이 private artifact 검증은 npm registry 공개
설치나 public URL 재다운로드를 증명하지 않습니다.

## 사전 조건

- Node.js 18 이상
- npm registry에서 `@bitkyc08/media-bridge` 조회 가능
- 테스트 중 사용할 포트가 비어 있음
- OpenCodex·Solar credential 원문을 문서나 로그에 기록하지 않음

## 설치와 최초 설정

```bash
npm install -g @bitkyc08/media-bridge
mb init
```

`mb init`에서 OpenCodex 주소, Media Bridge 포트, Solar 모델·endpoint·Secret 참조,
변환 기본값과 실패 시 Solar 전송 차단 정책을 설정합니다.

## 실행 검증

```bash
mb start
mb status --json
mb health --json
mb ready --wait --timeout 30
mb gui
```

지원 플랫폼의 첫 `mb start`는 npm package에 포함된 manifest를 기준으로 runtime artifact를 자동으로
선택·다운로드하고 SHA-256을 검증합니다. 사용자가 runtime URL, checksum 또는 Python 경로를 입력하지
않아야 합니다. 설치된 runtime의 플랫폼·version·SHA-256이 공개 release manifest와 일치하는지 기록합니다.

runtime artifact가 없거나 checksum 검증에 실패하면 `mb start`가 중단되어야 하며, 기존에 검증된
runtime이 있으면 그대로 보존되어야 합니다.
이 경우 테스트를 PASS로 기록하지 말고 runtime release 부족으로 기록합니다.

## 종료와 정리

```bash
mb service restart
mb stop
mb service uninstall
mb uninstall --keep-config
mb uninstall --delete-config
npm uninstall -g @bitkyc08/media-bridge
```

`--keep-config` 후에는 config가 남고 관리 runtime·service/PID state가 제거됐는지 확인합니다.
이어서 `--delete-config` 후에는 config가 제거되되 Media Bridge가 소유하지 않은 파일은 보존되는지
확인합니다. 마지막 npm 명령 후 `mb`와 `media-bridge` 명령이 사라졌는지 확인합니다.
종료 후 process, PID/state 파일, 테스트 포트가 남지 않았는지 확인합니다.

## 증거 기록

다음 항목을 각각 기록합니다.

- npm package version과 registry 설치 결과
- source commit, GitHub Actions workflow run URL/ID와 private artifact 이름
- 운영체제·아키텍처
- `mb init`, `start`, `status`, `health`, `ready`, `stop` 결과
- `mb uninstall` 설정 보존·삭제 선택, 비소유 파일 보호와 npm package 제거 결과
- runtime artifact 이름과 SHA-256
- 실제 실행 command가 관리 runtime인지와 Python 직접 호출 여부
- 실제 OpenCodex/Solar 호출 여부
- 실패 원인과 재현 명령

Node 계약 테스트, fixture 테스트, 로컬 `npm pack` 결과만으로 외부 설치 PASS를 선언하지 않습니다.
현재 공개 전 제품 상태 명칭은 `PUBLIC_RELEASE_BLOCKED`이며, runtime 구현 결정 대기 상태가 아닙니다.
