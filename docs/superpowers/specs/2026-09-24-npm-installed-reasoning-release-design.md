# npm 설치형 추론 등급 릴리스 후보 설계

## 상태

- 상태: 신산님 설계 승인
- 작업 브랜치: `codex/installed-reasoning-level-config`
- 후보 버전: `0.1.14`
- 범위: 설치형 `@cyhuh/media-bridge`의 후보 패키지 준비 및 설치 검증
- 제외: ysna/서버 배포, `main` 병합, 공개 GitHub Release/tag 생성, npm 공개 등록

## 1. 목적과 완료 조건

설치형 Media Bridge의 Media Bridge/Non-Vision LLM 추론 등급 기능을 새 npm 설치에서 사용할 수 있도록, 현재 기능 브랜치의 동일한 source commit으로 세 플랫폼 runtime과 npm 후보 패키지를 연결한다.

완료 조건:

1. Windows x64, Linux x64, Linux ARM64 runtime 산출물이 동일 source commit 및 후보 버전 `0.1.14`로 빌드되고 각 플랫폼 native verifier를 통과한다.
2. 후보 패키지 manifest가 세 runtime 산출물의 실제 SHA-256 및 이후 공개될 정식 asset URL을 가리킨다.
3. `npm pack`으로 만든 후보 tarball을 격리된 npm prefix/HOME에 설치할 수 있다.
4. 설치한 CLI가 후보 runtime을 검증·기동하고, 설정 화면에서 두 등급 선택기를 표시하며 API가 저장한 등급을 반환한다.
5. 후보 workflow가 public release나 npm publish를 수행하지 않는다.

## 2. 현 상태와 문제

- 설치형 동작 변경은 Python runtime `media_bridge_personal/npm_runtime.py`에 있으므로 npm CLI JS만 갱신해서는 기능을 배포할 수 없다.
- `packaging/npm/package.json`과 `runtime-manifest.json`은 `0.1.13`이다.
- `publish-npm-runtime-release.yml`은 버전, release tag, source commit, 각 플랫폼의 Actions run ID를 `0.1.13` 기준으로 고정한다.
- npm 계약 테스트도 `0.1.13`을 직접 단언한다.
- 따라서 기존 npm registry 설치는 기존 runtime을 계속 받으며, 기능 브랜치의 새 코드를 포함하지 않는다.

## 3. 설계

### 3.1 후보 전용 다중 플랫폼 빌드

기존 플랫폼별 runtime build workflow를 재사용할 수 있도록 `workflow_call` 입력으로 후보 버전을 받게 한다. 별도 후보 조정 workflow는 해당 브랜치의 source commit과 버전 `0.1.14`를 고정하여 세 플랫폼 build/verifier를 병렬 실행한다.

후보 조정 workflow는 설치형 runtime 및 npm packaging 소스 변경이 들어간 feature branch push에서만 실행되도록 범위를 제한한다. 사용자 설정이나 Provider secret은 빌드에 전달하지 않는다. 각 빌드 증거에는 플랫폼, source commit, artifact version, SHA-256, health 결과를 포함한다.

### 3.2 후보 manifest와 npm tarball

조정 workflow는 세 빌드 산출물의 이름·checksum·검증 evidence가 모두 동일 source commit 및 `0.1.14`에 대응하는지 확인한 후 후보 manifest를 생성한다. manifest의 URL은 추후 공개 Release asset 경로를 사용하지만, 후보 검증에서는 manifest를 임시 loopback URL로 치환해 공개 URL 없이 실제 checksum/download/install 경로를 시험한다.

후보 manifest, 플랫폼 산출물, `npm pack` tarball 및 검증 결과는 GitHub Actions workflow artifact로 보관한다. artifact 접근 범위는 저장소 visibility와 GitHub 권한을 따르며, 이를 private이라고 가정하지 않는다. 후보 산출물에는 Secret을 포함하지 않는다. 저장소의 release manifest/버전 메타데이터를 자동 변경하지 않는다. 후보 산출물은 정식 GitHub Release asset 또는 npm 배포물이 아니다.

### 3.3 격리 설치 검증

후보 tarball을 각 native runner의 격리된 npm prefix에 설치한다. 별도 HOME, 합성 secret, 임시 포트와 임시 runtime/config 경로를 사용한다. 검증은 runtime checksum 확인, 정상 기동/health, 설정 화면 필드, settings API 값 및 Non-Vision LLM 명시 등급 우선순위를 확인한다. 실제 Upstage 요청은 수행하지 않는다.

테스트가 끝나면 각 runner의 임시 process와 파일을 정리한다. 사용자 로컬 `127.0.0.1:8642` 설치나 설정은 후보 workflow에서 변경하지 않는다.

### 3.4 공개 릴리스 게이트

기존 공개 릴리스 workflow는 동적 버전·source commit·후보 artifact run을 입력으로 검증할 수 있게 고친다. npm publish job은 명시적 `release-v<version>` tag에서만 실행되도록 유지한다. 후보 build/tag만으로 GitHub Release 생성, public asset 업로드 또는 npm 게시가 일어나지 않도록 후보 workflow와 공개 workflow를 분리한다.

이 작업 단계에서는 공개 release workflow의 검증과 후보 설치까지 준비하지만, 공개 tag 생성·`npm publish`는 실행하지 않는다. 해당 공개 변경은 신산님의 별도 승인 후 진행한다.

## 4. 검증 기준

- Node test: npm CLI/runtime 계약, workflow trigger/input/permission, version·manifest·artifact identity, publish gate 회귀
- 각 플랫폼 native verifier: artifact checksum, 실행 파일 inventory, managed install/rollback/checksum reject, health 200
- 각 native runner: 후보 tarball 설치 및 설정 UI/API 확인
- `npm pack --dry-run` 및 실제 tarball 파일 목록 검사
- feature branch만 변경되었는지 확인; `main`, 서버 컨테이너, 사용자 8642 runtime은 변경하지 않음
- 전체 Python/npm 검증 결과와 기존 실패를 별도 기록; 미실행 플랫폼/검증은 PASS로 표기하지 않음

## 5. 위험과 제한

- 세 platform artifact 중 하나라도 source commit/version/checksum이 다르면 후보 조립을 실패시킨다.
- Actions artifact는 후보 보관물이며, 공개 Release URL을 사용할 수 있을 때까지 registry 설치를 대체하지 않는다.
- `npm pack`만으로 public registry 설치 가능성을 주장하지 않는다. 공개 npm 설치 가능 상태는 별도 승인된 tag/release/publish 이후에만 성립한다.
- GitHub Actions/OIDC 권한이 필요해지더라도 개인 GitHub 로그인, PAT, 계정 전환을 이용하지 않는다. 설정된 `github-cyhuh7950` SSH alias 외 계정 자격 증명을 사용하지 않는다.
- ysna-server, 설치형 8642 운영 runtime, DB 및 main 통합은 범위 밖이다.

## 6. 구현 순서

1. workflow contract 및 npm metadata 테스트를 먼저 추가하고 RED 확인
2. platform build workflow에 재사용 입력 계약 추가
3. branch-scoped candidate orchestration, artifact assembly, isolated install matrix 구현
4. hard-coded `0.1.13` release assumptions를 version/source/artifact evidence 검사로 교체
5. package/release 계약 테스트와 전체 관련 검증 수행
6. 후보 artifact evidence와 제한 사항을 `docs/WORK_STATUS.md`에 기록
