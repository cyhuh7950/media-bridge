# Media Bridge 작업현황

## 2026-09-23 — Provider 약어 저장 오류 수정

- Provider 수정 화면에서 기존 약어 `US`가 서버 계약의 소문자 형식과 맞지 않아 저장 요청이 422로 거부되던 문제를 확인했다.
- 편집 화면 초기화·입력·저장 요청 모두 Provider 약어를 소문자로 정규화했다. Provider 선택 목록과 API 키 저장 경로는 변경하지 않았다.
- 검증: Operations 14 passed, Web typecheck/build passed, `git diff --check` passed. 배포형 Control 재빌드·재기동 후 브라우저 Provider 저장 smoke를 수행한다.

## 2026-09-23 — OmniRoute 흐름 시험의 모델·추론 등급 분리 설정

- Test Lab의 `OmniRoute → Media Bridge 전체 흐름 시험`에 독립적인 공개 모델과 추론 등급 선택을 추가했다.
- 위의 전체 파이프라인 시험 선택값과 분리하며, OmniRoute 실행 시 아래 설정값을 `/test-lab/run` 요청에 전달한다.
- 검증: Test Lab 5 passed, Web typecheck/build passed. 배포형 Control 이미지 재빌드·재기동은 커밋 push 후 수행한다.

## 2026-09-23 — 모델과 내부 라우팅 책임 분리

- 모델 생성 화면에서 `내부 실행 라우팅`을 필수 입력·조회 항목으로 제거했다. 모델은 공개 `provider/model`, 기준 Non‑Vision LLM Provider, 모델별 추론 등급·capability만 관리한다.
- 모델에 라우팅 연결이 없는 경우 Data Plane은 snapshot의 첫 번째 활성 routing profile을 Media Bridge 기본 라우팅으로 사용한다. 활성 기본 라우팅이 없으면 기존 모델 Provider fallback을 유지한다.
- RED→GREEN 검증: 공개 모델 무라우팅 계약 및 기본 라우팅 선택 테스트 추가 후 Python 관련 unit 66 passed, Web Operations 13 passed, Web typecheck/build passed, 변경 Python Ruff passed.
- 미검증: 실제 브라우저에서 모델 생성·snapshot 발행 후 외부 Provider 호출과 WSL 재배포. 이번 변경은 로컬 작업 브랜치에만 반영했으며 설치형은 수정하지 않았다.

## 2026-09-23 — OmniRoute 호환 공개 모델·추론 등급 구현 진행

- `codex/manual-integrated-revision`에서 구현 중이다. 설치형은 수정·배포하지 않는다.
- Provider 등록은 외부 모델을 자동 공개하지 않고, Provider 약어(alias)만 자동 생성하며 수정할 수 있게 했다. 모델 관리에서 `provider/model` 공개 모델을 생성하고 내부 routing profile과 연결한다.
- `/v1/models`에는 등록된 공개 모델만 노출한다. Provider 등록만으로 모델이 생기지 않으며, OmniRoute/OpenRouter 등 route형 카탈로그는 upstream Provider 선택 목록에서 제외했다. 사용자 정의 Provider 입력은 유지한다.
- 외부 모델 선택은 미지정(기본 모델), `auto`(Media Bridge 내부 선택), 명시적 `provider/model`로 구분했다. 요청 추론 등급 → 공개 모델 설정 → Provider 설정 → Media Bridge 정책 기본값 순으로 적용하며 공개 표준값은 `low|medium|high`이다.
- Test Lab의 전체 파이프라인과 외부 클라이언트 흐름 시험 모두 공개 모델·추론 등급을 선택한다. Provider 화면의 Secret 환경변수 입력·표시 경로는 제거하고 Provider API key는 DB 보관 경로만 사용한다.
- 검증: 변경 Python Ruff 통과, control unit/packaging 74 passed, Web build 및 Operations/Test Lab 16 passed. Gateway unit은 33 passed, 3 failed이며 실패 중 downstream capability fixture는 수정 후 해당 테스트가 통과했고, 나머지는 기존 FakeDownstream 계약 assertion 및 만료일 fixture 문제로 미수정·미해결이다.
- checkpoint `5c5adad` 및 Data Plane 기동 보완 `9fe2f9c`를 `github-cyhuh7950` SSH alias 원격 branch에 push했다. WSL-server의 기존 배포형 디렉터리는 `.env`만 보존하고 `9fe2f9c` checkout으로 교체했다.
- WSL-server 기존 DB `0010_previous_csrf_digest`에 승인된 `0011_public_model_routing` migration을 적용했고, 기존 Secret은 서버의 보존된 `media-bridge-runtime/deploy/secrets`에서 새 배포 디렉터리로 복구·검증했다. Secret 원문은 출력하지 않았다.
- 배포형 Control/Data/DB를 새 이미지로 재기동했다. Control `172.27.253.53:18642` 및 Data Plane health가 healthy이고 Control `/`, `/login`, `/health`는 HTTP 200이다. Data Plane `/v1/models`는 인증 없이 HTTP 401로 차단된다. 설치형은 건드리지 않았다.
- Data Plane 최초 기동에서 `openai-vision` 하드코딩으로 실패한 문제를 확인해, 등록된 분석 Provider를 사용하고 Vision Provider가 없으면 optional backend로 기동하도록 `9fe2f9c`에서 수정했다. 현재 DB에는 분석 Provider `upstage-document-parse`, LLM Provider `upstage-solar`가 있고 공개 모델은 아직 0개이므로 `/v1/models` 공개 목록과 실제 LLM 호출은 Provider/라우팅/모델 등록 후 확인해야 한다.
- 남은 미검증: 브라우저 admin 로그인·Provider/라우팅/모델 등록 smoke 및 외부 Upstage 호출. 로컬 Gateway entrypoint 테스트 1건은 fixture 만료일이 현재 날짜와 겹친 기존 시간 의존 실패이며, 이번 변경 경로와 무관하다.

## 2026-09-22 — WSL 배포형 clean redeploy 및 초기 Control 기동 복구

- 신산님 지시를 최신 기준으로 적용한다: WSL 배포형 Media Bridge의 이전 리소스는 정리하고 기존 `/home/daon/deploy/media-bridge/.env`만 보존한다. 기존 WSL DB/볼륨은 재사용하지 않고 새 DB로 시작한다. 개인 설치형 런타임과 다른 프로젝트 리소스는 범위 밖이다.
- 최초 배포에서 DB 볼륨이 없을 때 시스템 Secret 6개를 생성하고 재배포 시 유효한 기존 파일을 보존하며, 일부 누락 또는 기존 DB만 존재하면 중단하는 `deploy/scripts/secret_bootstrap.py`를 추가했다. Provider credential 정본은 계속 DB다.
- 이전 배포형 전용 DB/asset/snapshot volumes 6개와 이미지 2개를 제거했고 기존 `/home/daon/deploy/media-bridge`에는 `.env`만 남겼다. 신규 DB/Control health 확인 후 임시 보관했던 이전 DB backup도 제거했다. 개인 설치형 런타임과 타 프로젝트 리소스는 보존했다.
- ysna-server에서 현재 운영 Control이 참조하는 pepper(메타데이터만 확인)를 사용자가 제안해 새 WSL Secret으로 원문 노출 없이 전송했다. 새 DB의 bootstrap 재검증은 `deployment_secrets_preserved`; 전체 Secret 파일 권한·소유자 기준을 통과했다.
- 최소 수정 commit `0da6282158d129c02f40dcd50ccee3090c3c6a0e`를 기존 원격 branch에 push하고 WSL checkout도 fast-forward했다. 수정 image `media-bridge-control:0.1.0`, image ID `sha256:321a95691cc2bce84afbb740fcf4a4823405379dbc383c7480812d9dbff56564`; Control과 신규 DB 모두 healthy, DB revision은 `0009_provider_reasoning_effort`다.
- 이 수정의 unit 결과: 회귀 테스트는 수정 전 `control_plane_migration_required`로 RED, `0009_provider_reasoning_effort`를 허용한 뒤 GREEN. `tests/control/unit` 및 migration rollback 검사 합계 70 passed, 변경 파일 Ruff와 `git diff --check` 통과.
- 신산님 지시에 따라 Control의 published port를 환경변수화하고, WSL `.env`에는 `172.27.253.53:18642`만 설정했다(파일 mode 0600, 나머지 기존 항목은 유지). 지정 branch commit `49f5051` 및 계약 테스트를 push하고 WSL checkout을 동기화한 뒤 Control만 재생성했다. Compose mapping은 `172.27.253.53:18642 -> 8081`; Windows에서 `/` HTTP 200, Control healthy, DB healthy 및 revision `0009_provider_reasoning_effort`를 확인했다. 개인 설치형은 계속 `127.0.0.1:8642` 및 `172.17.0.1:8642`에서 실행 중이다.
- 직접 HTTPS 시험은 TLS `wrong version number`로 실패했다. Control 컨테이너는 TLS가 아닌 HTTP `8081`을 제공하고 Admin API는 HTTPS scheme/Host/Origin을 강제한다. health API는 HTTP 200이지만 로그인·onboarding은 usable하다고 입증되지 않았다. bootstrap POST는 안전검토에서 상태변경 위험으로 거부되어 수행하지 않았다. HTTP를 허용하도록 보안을 낮추지 않았다.
- Data service 및 Provider/Snapshot 기반 Gateway 검증은 미수행이다. 다음에는 18642 앞에 승인된 TLS termination과 인증서 경로를 구성해야 사용자 로그인/onboarding을 검증할 수 있다.

판정: PARTIAL — Control/DB health와 18642 HTTP route 확인; HTTPS 로그인/onboarding 및 Data/Gateway 검증은 TLS ingress 필요로 미완료
정본: `docs/design/DESIGN.md`, `docs/WORK_PLAN.md`, `docs/WORK_STATUS.md`, `docs/superpowers/specs/2026-09-22-llm-reasoning-levels-design.md`
작업계획: 배포형은 실행 가능한 지원 Non‑Vision LLM의 Provider/API/model별 설정과 downstream 반영, 설치형은 Upstage Solar 설정. 분석 Provider 및 N:N 연결 보존. 계획 구현은 `codex/manual-integrated-revision`에서만 진행하며 다른 branch/worktree는 생성하지 않음. 신산님은 nullable Provider DB column 및 migration을 승인했고 신규 WSL DB에 `0009_provider_reasoning_effort`를 적용했다. ysna-server DB에는 migration을 적용하지 않았다.
Git: `codex/manual-integrated-revision` / 원격 추적 `origin/codex/manual-integrated-revision` / 추가 branch 생성 금지
최근 완료 증거: `media_bridge_gateway/entrypoints.py`에서 기동 시 DB의 `upstage-solar`를 직접 읽어 Solar backend를 만들고, `GatewayTransactionFactory`에 같은 고정 downstream을 전달하는 것을 확인함. `media_bridge_control/configuration.py`의 snapshot에는 Provider 목록이 있지만 이 entrypoint는 snapshot Provider 목록으로 LLM downstream을 선택하지 않음.
현재 변경: 공통 resolver, Provider nullable `reasoning_effort`/`0009` migration, Control API·snapshot 및 Provider LLM 등록/수정 UI, Gateway의 DB Provider/model별 LLM dispatch, 설치형 Upstage Solar 선택 및 downstream 전달을 같은 feature로 구현 중. API key credential은 snapshot/file이 아니라 기존 암호화 DB를 Provider UUID로 조회한다. 분석 Provider와 N:N 라우팅은 변경하지 않는다.
실행·검증 결과: Task 1 resolver 43 tests와 Ruff 통과. Task 2 unit 4 tests, API/snapshot/schema checks 및 offline Alembic SQL 통과; PostgreSQL 통합 fixture 미검증. Task 3 Operations UI 12 tests, 변경 파일 ESLint, typecheck/build 통과; 전체 lint는 수정하지 않은 TestLab 파일에서 기존 오류 15개. Task 4 mock/unit/snapshot 72 passed. Task 5 adapters 15 passed; Task 6 personal/package suites 58 passed; 합산 관련 회귀 suite 88 passed. 설치형 작업 대상 Ruff, mypy, compileall 통과.
오류와 조치: Windows 기본 pytest 임시 경로 ACL 오류는 worktree 내 `.pytest-tmp-task4` 경로로 우회. `127.0.0.1:55432` PostgreSQL fixture는 `connect_timeout=1` 기준 connection timeout; Docker CLI와 WSL 접근은 불가하고 운영 DB는 테스트에 사용하지 않음. Task 4 전체 지정 Gateway suite는 `test_responses_transaction.py`의 기존 Vision fixture 기대값 2건(`red terminal`을 기대하나 실제 sanitization 입력은 OCR `ERROR 104`만 포함)에서 실패했으며 관련 test/gate/service/sanitizer는 이 branch에서 수정하지 않음. Gateway DB credential 통합 테스트는 PostgreSQL 연결 시간초과로 시작 불가.
미검증·승인 경계: Task 2 PostgreSQL API/migration/snapshot 통합 및 Task 4 DB credential fixture는 PostgreSQL fixture가 없어 미검증. Task 4 Gateway transaction suite의 기존 Vision 입력 기대값 2건은 현 구현 응답과 불일치. Task 3 전체 lint gate는 수정되지 않은 TestLab 파일의 baseline 오류. Full pytest/npm suite, DOCX visual render, 외부 Provider 호출, ysna의 실제 commit/image/health, 운영 DB migration 적용 및 배포는 미수행. 운영 DB 적용·배포 권한을 새로 넓히지 않는다.
오류 횟수·조치: PostgreSQL fixture unavailable 1회; 전체 lint baseline 1회; Gateway transaction Vision assertion 불일치 2건; DOCX render가 번들 LibreOffice 미탑재로 중단. 설치형 설정/API/downstream 회귀는 테스트 우선 RED→GREEN, 관련 personal/package suite 58 passed.
정확한 다음 조치: DOCX 렌더 runtime 경로를 확보해 visual QA를 완료하고, DB 통합·기존 Gateway assertion 판정 경계를 해결한 뒤 전체 Task 7 검증을 수행한다. ysna DB에 migration을 적용하거나 배포하지 않는다.

## 2026-09-22 — 배포형 reasoning migration gate 보완

- 배포 기동 migration 스크립트의 지원/목표 revision이 `0008_model_provider`로 고정되어 있어 `0009_provider_reasoning_effort`가 있는 이미지도 새 schema에서 시작하지 못하는 원인을 확인했다.
- `deploy/scripts/migrate.py`의 지원 revision, 구 schema에서의 forward 허용 목록, apply 목표 및 사후 검증을 `0009_provider_reasoning_effort`로 정렬했다. Provider DB의 nullable reasoning 설정만 추가하며, 기존 credential 저장 경로·설치형 runtime·Provider Secret은 변경하지 않았다.
- 회귀 검증: migration/package/control/gateway/provider backend 지정 테스트 44 passed; 배포형 관련 Ruff passed; Web 9 files/36 tests passed; typecheck/build passed.
- 테스트를 위해 별도 `.venv-deploy-verification`를 생성했다. WSL-server 운영 DB revision과 backup은 아직 미확인이다. 이 이미지를 기동하면 entrypoint가 migration을 자동 apply하므로 운영 DB 적용 승인 전에는 container를 시작하지 않는다.
- 다음: 지정 branch의 변경을 검토·checkpoint한 뒤 배포 서버의 compose·DB revision·backup 및 host bind 경로를 비밀값 없이 확인한다. `0009`는 `providers.reasoning_effort VARCHAR(16) NULL` 추가이며 rollback은 column drop이므로, DB 적용 직전 신산님께 대상 DB·revision·backup·rollback을 제시해 승인을 확인한다.

## 2026-09-22 — Provider 정본 및 WSL 배포 차단점

- Compose가 DB Provider credential을 이미 읽는 Gateway와 별도로 OCR/Vision/Solar API-key Secret 파일을 필수 선언하고 Vision endpoint/model도 환경변수로 요구하는 회귀를 확인했다. 배포형은 DB Provider의 endpoint/model/encrypted credential만 사용하도록 해당 3종 파일 Secret과 Provider endpoint/model 환경변수를 제거하고, Vision Provider를 DB에서 resolve하도록 수정했다. 설치형 generic backend 동작은 유지했다.
- WSL의 실제 설치형 프로세스는 `127.0.0.1:8642`와 Docker relay `172.17.0.1:8642`에서 응답 중이며 중단·재설치하지 않았다. 요청 IP `172.27.253.53:8642`는 현재 연결 불가다. 배포 컨테이너는 없고, `/home/daon/media-bridge` checkout은 없다.
- `/home/daon/deploy/media-bridge`는 dirty `main`이며 `origin/main` 대비 ahead 324/behind 253이므로 변경하지 않았다. 기존 Docker DB volumes `media-bridge_database`, `media-bridge-wsl_database`가 별도 compose project 소유로 존재하지만 대상 DB와 revision은 확인되지 않았다. 두 볼륨 모두 보존한다.
- 현재 Control API와 settings는 HTTPS 전용이며 평문 요청은 `https_required` 400으로 거부한다. 요청받은 `http://172.27.253.53:8642` 바인딩·HTTP 보안 우회는 적용하지 않았다. 안전한 HTTPS 진입 경로가 필요하다.
- Compose의 비-Provider 시스템 Secret 6개(db password, DB URL, security pepper, snapshot key pair, receipt secret)는 서버 기본 경로에 모두 없다. Provider API-key Secret 파일은 제거 대상이며 새로 만들지 않았다. Compose 기동 시 migration이 자동 apply되므로 확인되지 않은 기존 볼륨으로 기동하지 않았다.
- 추가 검증: migration + gateway/provider/backend + 신규 compose contract 선택 테스트 46 passed, 변경 Python Ruff passed. 전체 packaging suite는 68 passed/7 skipped/6 failed; 실패는 Windows 전용 `os.fchmod`, 기존 compose-network assertion, public docs tree assertion, PowerShell subprocess encoding 등이며 상세는 실행 결과 참조. 앞서 Web 36 tests/typecheck/build도 통과.
- 배포 재개 조건: HTTPS URL/인증서 진입 방식 확정, 새 격리 DB 사용 또는 기존 DB 중 정확한 대상 선택, 6개 시스템 Secret 생성·보관 승인, migration 대상·backup 승인. 설치형 runtime과 이전 volume 정리는 별도 지시 없이는 하지 않는다.

## 2026-09-22 — WSL-server deployment checkpoint

- 신산님 지시로 WSL 접속은 `WSL-server` SSH alias를 사용한다. 최초 확인에서 로컬 WSL distro를 잘못 대상으로 삼았으나, SSH alias 설정을 확인한 뒤 권한 승인 방식으로 접속했다.
- 원격 `/home/daon/deploy/media-bridge`는 `main` HEAD `be56d404af24966ac53f22e0804dbff3e32d91fa`, `origin/main` 대비 ahead 324 / behind 253이며 `docs/install/linux.md` 수정과 `docs/design/` untracked 상태다. 신산님은 이것이 이전 개발 내용이므로 제거 가능하다고 지시했으나 아직 정리하지 않았다.
- 원격 8642는 설치형 런타임이 이미 실행 중이다. `/home/daon/.local/bin/mb status`=`running 127.0.0.1:8642`, `mb health --json`=`healthy=true,status=200`; `172.17.0.1:8642` relay도 HTTP 200이다. 실행 바이너리는 `/home/daon/.media-bridge/runtime/bin/media-bridge-runtime`; config 및 credential 원문은 읽지 않았다.
- 요청 URL의 호스트 IP `172.27.253.53:8642`는 원격에서 HTTP 연결 실패했다. 현재 listener는 `127.0.0.1:8642`와 Docker relay `172.17.0.1:8642`뿐이라 WSL bind 주소 설정/서비스 재기동이 필요하다. 아직 설정이나 프로세스를 변경하지 않았다.
- 신산님은 WSL에 배포해 `http://172.27.253.53:8642`에서 확인하도록 지시했다. 현 시점 source 변경 배포는 미수행이며, source branch 변경은 미커밋 상태다. Provider·onboarding focused tests 15 passed, 전체 Web tests 36 passed, typecheck/build 및 설치형 회귀 27 passed, 관련 personal Python 파일 Ruff 통과.
- 전체 gate는 미통과/미완료: repository Ruff 10 errors (`media_bridge_control/api.py`의 `connections` 미정의 참조 포함), Web lint 15 errors (`TestLabPage*`), 전체 pytest는 71개 진행 후 장시간 무출력으로 중단. WSL DB migration 필요 여부·대상은 아직 판별/적용하지 않았다.
- WSL runtime 교체, `/home/daon/deploy/media-bridge` 정리, DB migration, commit/push는 미수행. 다음은 branch 전체 gate 문제 원인을 분리하고, 사용자가 승인한 이전 checkout 정리 범위와 설치형 runtime 업데이트/rollback 절차를 확인한 뒤 exact commit 배포 여부를 결정하는 것이다.

## 2026-09-19 — Provider catalog schema checkpoint

- `975f940` (`feat: add managed provider catalog schema`) pushed to `origin/codex/auth-totp-recovery-email`.
- Provider에 `llm`, `catalog_id`, `protocol`, `capabilities`를 추가하고 catalog 선택 시 endpoint/protocol/capabilities를 서버에서 보완한다.
- Alembic `0004_managed_provider_catalog`을 추가했다. 기존 legacy provider는 nullable metadata로 보존하고, 데이터가 있는 managed provider의 downgrade는 거부한다.
- 통합 PostgreSQL 검증은 WSL-server 실행 전까지 미검증으로 유지한다.

## 2026-09-19 — Provider catalog selection UI checkpoint

- `f5c14d4` (`feat: add provider catalog selection UI`) pushed to `origin/codex/auth-totp-recovery-email`.
- 설치형 onboarding과 배포형 operations 화면에서 분석/Non-Vision LLM 유형과 카탈로그 Provider를 선택한다.
- 선택한 카탈로그의 endpoint, protocol, capability, 권장 Secret 환경변수 이름을 자동 채우며 Secret 원문은 저장하지 않는다.

## 2026-09-19 — N:N routing profile checkpoint

- 분석 Provider와 Non‑Vision LLM Provider의 ID 목록을 각각 저장하는 `routing_profiles`와 관리 API를 추가했다.
- `priority`, `fallback`, `health`, `cost` 전략을 선택할 수 있고, 서버가 Provider 종류·존재 여부를 검증한다.
- Console에 여러 Provider를 선택하는 Routing 화면과 `/routing-profiles` 경로를 추가했다.

## 2026-09-19 — WSL PostgreSQL verification

- WSL-server 임시 checkout `465ae12`에서 전용 PostgreSQL 컨테이너를 생성해 `test_migrations.py`와 `test_connection_migration.py`를 실행했다: 4 passed.
- 같은 환경에서 `test_configuration_api.py`를 실행했다: 2 passed.
- 테스트 컨테이너 `media-bridge-test-pg`는 검증 후 제거했다.

## 2026-09-19 — Provider selection primitive

- `media_bridge_gateway/provider_selection.py`에 enabled·capability·health 필터와 priority/fallback/health/cost 선택 규칙을 추가했다.
- 후보가 없으면 `provider_route_unavailable`로 fail-closed 처리한다.
- Gateway snapshot/runtime wiring과 실제 downstream 호출 연결은 아직 남아 있다.

## 2026-09-19 — OpenAI-compatible model discovery endpoint

- 인증된 Data Plane에 `GET /v1/models`를 추가했다.
- 서명된 snapshot의 안전한 `models` 목록만 OpenAI 호환 `{object,data}` 형식으로 반환한다.
- `/v1/models`는 `responses:invoke` scope와 동일한 Data Plane 인증을 사용한다.
- 모델 목록은 실제 snapshot의 `registry.models` 구조와 top-level 호환 구조를 모두 읽는다.

## 2026-09-18 — 배포형 범위 초안

- 신산님 결정: 설치형과 구분되는 배포형은 외부 Endpoint, 사용자별 API key, 분석 Provider와 Non-Vision LLM Provider, N:N routing, 비용·분석·모니터링·감사 기능을 포함해야 한다.
- 결정된 기본 연결: 분석 Provider와 Non-Vision LLM Provider는 라우팅 프로필을 통한 N:N 연결이며 priority/fallback/health/cost 정책으로 자동 선택한다.
- 결정된 외부 연동: OmniRoute에는 설치형 localhost가 아니라 배포형 HTTPS Media Bridge Endpoint를 OpenAI 호환 Provider로 등록한다.
- 미결정: Anthropic 호환 세부 계약, OmniRoute의 tenant 헤더 전달 방식, 1차 Provider catalog의 최종 승인과 가격표 정책.

## 2026-09-19 — ysna-server deployment checkpoint

- Deployed branch commit `93a8312` to `/home/ubuntu/deploy/media-bridge` and rebuilt `media-bridge-control:0.1.0-deploy`.
- Applied approved Alembic migration `0004_managed_provider_catalog -> 0005_routing_profiles`; database reports `0005_routing_profiles`.
- Control Plane container is healthy and serving on its configured HTTPS proxy path.
- Data Plane container is not healthy because the snapshots volume has no signed `active.json` yet; initial setup/publish is required before gateway traffic can run.
- User smoke test remains pending by request. No user credentials or secret values were printed.

## 2026-09-19 — Provider setup optionality and catalog query fix

- `3f395ab` fixes the admin API path validator to preserve approved query parameters, so `/provider-catalog?kind=analysis|llm` can load.
- Provider onboarding now states the connection is optional and exposes an explicit skip-to-console action.
- Web tests (9 targeted), lint, TypeScript check, and production build passed.
- Deployed the updated Control image to ysna-server; Control container is healthy. A fresh login is required after the container recreation.
- Data Plane remains waiting for the initial signed snapshot, as previously recorded.

## 2026-09-19 — pre-snapshot console access fix

- `37aad3d` allows the administrative console and setup navigation before the first signed snapshot; the snapshot remains required only for gateway traffic.
- Targeted guard/API tests (10 passed), lint, TypeScript check, and production build passed.
- Rebuilt and redeployed Control on ysna-server; container is healthy.

## 2026-09-19 — encrypted Provider API key deployment

- `e051d8a` adds encrypted Provider API key persistence using the existing SecurityContext Fernet key; Provider responses expose only `has_api_key`.
- Provider create/onboarding and operations forms accept an API key without requiring an environment-variable reference.
- `0006_provider_api_keys` adds the encrypted column and permits DB-backed references. The migration was applied on ysna-server after replacing the existing provider secret constraint transactionally.
- Control image rebuilt and redeployed; Control and PostgreSQL containers are healthy. Data Plane remains snapshot-dependent.
- Web targeted tests (10), lint, TypeScript check, and production build passed before deployment.

## 2026-09-19 — Provider CRUD 화면 표준 수정·ysna-server 재배포

- `7998cb3` adds the standard Providers list actions: `Provider 등록` opens a dialog, each writable row has `수정`, and selected rows can be removed with `선택 삭제` after confirmation. Viewer remains read-only.
- Regression coverage added for registration dialog, edit dialog prefill, and bulk DELETE requests. Web tests `29 passed`, lint passed, TypeScript check and production build passed.
- Rebuilt and redeployed `media-bridge-control:0.1.0-deploy` on ysna-server from the pushed branch commit.
- Deployment initially restarted because existing Secret files were `ubuntu:ubuntu 0400` while the image runs as UID `10001`; values were not changed. Secret ownership was corrected to `10001:10001` with mode `0400`; Control and PostgreSQL are healthy afterward.
- Data Plane remains restarting because the signed snapshot is still absent; this is outside the Provider screen change and requires initial snapshot publish before gateway traffic.

## 2026-09-19 — ysna public 502 upstream network repair

- Public `https://media-bridge.sinsan.kr` returned OpenResty 502 because Nginx Proxy Manager was attached only to `proxy-network`; its configured upstream `media-bridge-control` is on `media-bridge_product`.
- Control and PostgreSQL were healthy; Data Plane remained snapshot-dependent and was unrelated to the Control console 502.
- Connected the existing `nginx-proxy-manager` container to Docker network `media-bridge_product` without changing source, secrets, or database data.
- Verification: NPM resolved `media-bridge-control` at `172.26.0.2`, upstream health returned HTTP 200, and the public URL returned HTTP 200.

## 2026-09-19 — 세션 복구 후 Provider 쓰기 권한 수정

- 원인: `/admin/v1/me`가 `username`과 `role`만 반환해 새로고침 후 프런트 CSRF 상태가 `null`이 되었고, 관리자도 Provider 쓰기 UI가 숨겨졌다.
- 수정: 세션 복구 시 백엔드가 새 CSRF 토큰을 발급하고, 프런트가 이를 메모리 상태에 반영하도록 했다. 기존 CSRF 검증은 유지한다.
- 검증: Web 테스트 `29 passed`, lint, TypeScript 검사, production build, Python `compileall` 통과. PostgreSQL 통합 테스트는 Windows 로컬 fixture 기동이 멈춰 미검증이며 통과로 표시하지 않았다.
- 다음 조치: 이 커밋을 ysna-server Control 이미지로 배포하고 공개 `/providers`에서 새로고침 후 관리자 등록 버튼과 실제 등록/수정/삭제를 확인한다.
- 배포 완료: `7fcf220` 기준 Control 이미지를 ysna-server에서 재빌드·재기동했고 컨테이너 health가 `healthy`가 되었다. 공개 `/`와 `/providers`는 HTTP 200을 반환했다.
- Data Plane은 서명된 초기 snapshot 부재로 계속 재시작 중이며, 이번 관리자 콘솔 수정과 무관하다. 브라우저 관리자 smoke는 신산님이 수행한다.

## 2026-09-19 — 카탈로그 표시명 Provider 저장 오류 수정

- 원인: 카탈로그 표시명 `Upstage Document Parse`가 공백을 포함한 Provider 이름으로 전송되어 서버 식별자 검증에 거부되었다.
- 수정: 카탈로그 선택 시 화면 표시명은 유지하고 저장 이름은 안정적인 `provider_id`(`upstage-document-parse`)로 자동 입력한다.
- Web 테스트 `29 passed`, lint, TypeScript 검사, production build 통과. ysna-server Control 재배포 후 공개 `/providers`에서 관리자 저장 동작을 확인한다.
- 배포 완료: `18745fd` 기준 Control 재빌드·재기동 후 health `healthy`; 공개 `/`와 `/providers` HTTP 200 확인. Provider 등록 화면의 실제 저장 smoke는 신산님이 수행한다.

## 2026-09-19 — 콘솔 로그아웃 버튼 추가

- 헤더에 인증된 사용자용 `로그아웃` 버튼을 추가해 CSRF 보호 `/admin/v1/auth/logout` 호출 후 로그인 화면으로 돌아가도록 했다.
- 회귀 테스트를 추가했고 Web 테스트 `30 passed`, lint, TypeScript 검사와 production build가 통과했다.
- 다음 조치: 이 커밋을 ysna-server Control 이미지로 재배포하고 공개 URL의 헤더 로그아웃 버튼 노출을 확인한다.

- 배포 완료: `4ca6def`에서 Control 이미지를 재빌드·재기동했고 올바른 Ed25519 Secret 매핑 후 health가 `healthy`가 되었다. 공개 `/`와 `/providers`는 HTTP 200을 반환한다.
- 배포 중 원격 전용 Compose 파일을 보존하지 않은 rsync 옵션으로 삭제하는 오류가 1회 발생했다. Secret 값과 DB/볼륨 데이터는 변경되지 않았고, 기존 컨테이너 설정을 확인해 `compose.ysna.yaml`을 Secret 원문 없이 복원·구문 검증했다.
- Data Plane은 기존과 같이 서명된 초기 snapshot 부재로 재시작 중이다. 실제 로그아웃 클릭 smoke는 신산님이 공개 URL에서 확인하면 된다.

## 2026-09-19 — 로그아웃 후 로그인 오류 표시 수정

- 원인: 로그아웃 후 `anonymous` 상태의 `errorCode`가 비어 있어도 로그인 실패 경고를 렌더링했다.
- 수정: 실제 오류 코드가 있는 경우에만 경고를 표시하고, 로그아웃 후 로그인 화면은 깨끗하게 표시한다.
- Web 테스트 `30 passed`, lint, TypeScript 검사와 production build 통과.
- ysna-server 배포 설정에 프록시 `FORWARDED_ALLOW_IPS=172.26.0.3`을 복구해 공개 로그인 요청이 `https_required`로 거부되지 않도록 했다. `admin/admin` API 응답은 이제 예상된 `totp_required`다.
- 배포 완료: `1cd737c` 기준 Control 이미지를 재빌드·재기동했고 health가 `healthy`; 공개 `/`와 `/providers`는 HTTP 200이다. 브라우저에서 로그아웃 후 로그인 화면에 오류 경고가 남지 않는 것을 확인했다.

## 2026-09-19 — 콘솔 기본 언어 한국어 통일

- 좌측 메뉴, 대시보드·Provider·라우팅·모델·정책·스냅샷·감사·시스템·연결·테스트 랩 화면의 사용자 노출 문구를 한국어로 통일한다.
- `upstage-document-parse`, `upstage-solar`, Endpoint URL과 같은 Provider 식별자·고유명사·기술 값은 원문을 유지한다.
- Web 테스트 `30 passed`, lint, TypeScript 검사와 production build 통과 후 ysna-server에 재배포한다.
- 배포 완료: `8c6e555` 기준 Control 이미지를 재빌드·재기동했고 health가 `healthy`; 공개 HTML은 최신 한국어 UI 번들을 제공하며 `/`·`/providers`는 HTTP 200이다.

## 2026-09-19 — 관리 화면 표준화 및 라우팅 프로필 일괄 삭제

- 라우팅 프로필, 모델, 정책, 접근 키, 연결 화면을 목록 중심으로 정리하고 등록·수정은 팝업, 삭제·폐기는 선택 일괄 작업으로 통일했다.
- 라우팅 프로필은 분석 Provider와 Non‑Vision LLM Provider의 N:N 연결을 유지하며 우선순위·대체 경로·상태 우선·비용 우선 전략을 한국어로 표시한다.
- 라우팅 프로필 DELETE API를 추가했다.
- Web 테스트 30 passed, lint와 TypeScript/build 통과. Python compileall·git diff --check 통과.
- ysna-server 재배포와 실제 브라우저 smoke는 다음 단계다.

## 2026-09-19 — 관리 화면 표준화 배포

- `0aae60f`를 ysna-server Control 이미지로 재빌드·재기동했다.
- Control 컨테이너 상태 `healthy`, 공개 `https://media-bridge.sinsan.kr/` 및 정적 번들 응답 HTTP 200을 확인했다. 공개 URL의 로컬 인증서 주체 불일치로 Windows curl은 `-k` 검증을 사용했다.
- Data Plane의 서명 snapshot 의존 상태는 기존과 동일하며 이번 Control 화면 변경 범위가 아니다.

## 2026-09-19 — Provider 선택 모델과 기준 모델

- Provider 카탈로그에 기준 모델을 추가했다.
- Provider 등록·수정 팝업에서 `기준 모델 (선택)`을 지정할 수 있으며, 비워두면 카탈로그 기준 모델을 자동 사용한다.
- Provider 응답에 적용 모델을 표시하고 `0007_provider_models` migration으로 사용자 지정 모델을 저장한다.
- Web 테스트 30 passed, lint·TypeScript·build·ruff·compileall 통과. 기존 PostgreSQL 통합 테스트는 로컬 fixture 기동 지연으로 미검증이다.
- 다음 단계: 커밋 후 ysna-server에 migration 적용과 Control 재배포, 공개 URL 확인.

## 2026-09-19 — Provider 기준 모델 migration guard 수정 및 재배포

- `9e69566`에서 배포 마이그레이션 스크립트가 `0007_provider_models`를 지원하고 해당 head까지 자동 적용하도록 수정했다.
- ysna-server 재배포 시 `0006_provider_api_keys -> 0007_provider_models`가 적용되었고 DB `alembic_version`은 `0007_provider_models`이다.
- Control 및 PostgreSQL 컨테이너는 `healthy`이며 Control 로그에서 migration 완료와 Uvicorn 기동을 확인했다.
- 서버 내부 공개 URL 확인: `/`, `/providers`, `/routing`, `/models` 모두 HTTP 200. Data Plane은 기존과 같이 서명된 초기 snapshot 부재로 재시작 중이다.
- 로컬 Windows에는 Python 실행기가 없어 migration pytest를 실행하지 못했다. Web 30 tests, lint, TypeScript/build와 배포 전 compileall 결과는 앞선 커밋 검증을 유지한다.

## 2026-09-19 — DB API 키 수정 팝업 자동값 검증 오류 수정

- DB에 저장된 Provider를 수정할 때 자동 표시되는 `provider_api_key`를 환경변수 이름 정규식으로 검증하던 UI 오류를 수정했다.
- DB 참조는 `Secret 저장 위치` 읽기 전용으로 표시하고, 환경변수 참조에만 대문자 환경변수 형식을 적용한다.
- Web Operations 테스트 6개 통과, lint와 TypeScript/build 통과. ysna-server 재배포 후 수정 팝업에서 저장 smoke를 확인한다.

- 배포 완료: `abeab1f` 기준 Control 이미지를 ysna-server에서 재빌드·재기동했고 Control과 PostgreSQL이 `healthy`이다.
- 공개 `/` 및 `/providers`는 서버 내부 확인 기준 HTTP 200을 반환한다. DB Provider 수정 팝업의 저장 smoke는 신산님이 브라우저에서 확인한다.

## 2026-09-19 — DB API 키 표시 문구 개선 재배포 확인

- `d9ecc9f`에서 DB 내부 식별자 `provider_api_key`를 수정 팝업에 노출하지 않고 `DB에 저장된 API 키 사용 중`으로 표시하도록 변경했다.
- Operations 테스트 6개, lint, TypeScript 검사, production build 통과 후 ysna-server에 재배포했다.
- Control 컨테이너는 `healthy`, 공개 `/`와 `/providers`는 HTTP 200이다.
- Chrome Provider 수정 팝업을 강제 새로고침 후 실제 확인해 최신 표시 문구가 노출되는 것을 확인했다.

## 2026-09-19 — Provider Secret 내부 정보 완전 비표시

- 신산님 결정에 따라 `provider_api_key`와 Secret 저장 위치를 Provider 목록·수정 팝업에서 모두 제거했다.
- 목록은 키 원문이나 내부 식별자 대신 `등록됨` 상태만 표시하고, 수정 팝업은 API 키 변경 입력만 제공한다.
- Operations 테스트 7개, lint, TypeScript 검사, production build 통과.
- `04e1987` 기준 ysna-server 재배포 완료. Control `healthy`, 공개 `/`·`/providers` HTTP 200.
- Chrome에서 강제 새로고침 후 목록의 `등록됨`과 수정 팝업의 Secret 필드 비표시를 실제 확인했다.

## 2026-09-19 — 한국어 라우팅 프로필 이름 저장 오류 수정

- 원인: 라우팅 프로필 이름 스키마가 ASCII 문자만 허용해 `기본 문서 분석` 같은 한국어 이름을 거부했다.
- `RoutingProfileCreate/Update.name` 검증을 Unicode 이름을 허용하는 공백 규칙으로 변경하고, 한국어 표시 이름 회귀 테스트를 추가했다.
- 로컬 검증: 라우팅 프로필 단위 테스트 3개, Operations 웹 테스트 7개, lint, TypeScript/build, Python compileall 통과.
- `1ca267a` 기준 ysna-server Control 이미지를 재빌드·재기동했다. Control 컨테이너는 `healthy`이며 공개 `/`·`/routing-profiles`는 HTTP 200이다.
- 브라우저에서 실제 저장 버튼을 누르는 사용자 smoke는 신산님이 확인한다.

## 2026-09-19 — 모델 Provider 지정 및 접근 키 목록 표시 수정

- 모델 등록·수정 팝업에 Non-Vision LLM Provider 선택을 추가하고, 저장 시 선택한 Provider를 함께 검증한다.
- 모델 capability 레코드에 Provider 연결을 저장하도록 `0008_model_provider` 마이그레이션을 추가했다.
- 정책 등록 기본 이름을 `기본 미디어 보안 정책`으로 변경하고 한국어 정책 이름을 허용했다.
- 접근 키 목록에서 selector 일부가 상태 열에 노출되던 렌더링 오류를 제거하고, API의 `revoked` 값으로 `활성`·`폐기`를 표시하도록 수정했다.
- 웹 테스트 7개, lint, TypeScript/build, Python compileall 통과. ysna-server 재배포 후 접근 키 폐기와 모델·정책 등록 smoke를 확인한다.

## 2026-09-19 — 0008 마이그레이션 적용 경계 수정

- Control 시작 마이그레이션 스크립트의 지원 목록과 단계 검증에 `0008_model_provider`를 추가했다.
- 초기 재배포에서 0007에 머물러 502가 발생했으나, 수정 후 DB head가 `0008_model_provider`로 적용되고 Control이 `healthy`가 됐다.
- 공개 `/`, `/models`, `/credentials`, `/policies`는 HTTP 200을 확인했다.

## 2026-09-20 — Test Lab routed upstream/downstream execution

- Test Lab은 항상 활성 라우팅 프로필을 선택하고, 선택한 라우팅의 analysis Provider로 파일을 실제 전송한 뒤 추출 텍스트를 LLM Provider에 전달한다.
- 결과 패널은 `extractedText`, `forwardedText`, `originalMediaForwarded`, `answer`를 포함한 실제 처리 결과 JSON을 표시한다. 변환 profile·수동 endpoint·API key 입력은 제거된 상태다.
- Provider 카탈로그의 base endpoint(`/v1`)는 downstream protocol에 맞는 `/chat/completions` 또는 `/responses`로 보정하고, Document Parse OCR 옵션을 함께 전송한다.
- 웹 Test Lab 테스트 3개, TypeScript/build, Python ruff·compileall 통과. `317b012` 기준 ysna-server 재배포 후 `/test-lab` HTTP 200 확인.
- PostgreSQL integration `test_test_lab_api.py`는 기존 preview 검증 계약을 전제로 해 새 실제 호출 계약에 맞춘 별도 갱신이 필요하며, 이번 확인에서 실행이 정체되어 PASS로 판정하지 않았다.

## 2026-09-20 — Test Lab managed access-key selection

- OmniRoute → Media Bridge 시험의 키 라벨을 OmniRoute API key에서 Media Bridge 접근 키로 수정했다.
- 접근 키 관리 목록에서 `responses:invoke` 권한이 있고 폐기되지 않은 키를 선택할 수 있게 했다. 원문 키는 일회성 발급 정책상 서버에서 복구하지 않고, 사용자가 보관한 `mbc_...` 원문을 별도 입력한다.
- TestLabPage 웹 테스트 4개와 TypeScript/build 통과.
- `033295c`를 ysna-server `/home/ubuntu/deploy/media-bridge-033295c`에 배포했고 Control 컨테이너 `healthy`를 확인했다. 기존 `tests/control/integration/test_configuration_api.py`와 `.pr-body.md`는 미관련 dirty 상태로 보존했다.

## 2026-09-20 — Test Lab redundant selector and error wording cleanup

- Media Bridge 접근 키 관리 목록 선택 상자는 호출에 사용되지 않는 식별자 표시였으므로 제거했다.
- 오류 문구의 `OmniRoute endpoint/API key` 표현을 `Media Bridge endpoint/접근 키 원문`으로 수정했다.
- TestLabPage 웹 테스트 4개와 TypeScript/build 통과. `36f96fa`를 ysna-server에 배포했고 `/test-lab` HTTP 200 및 Control `healthy`를 확인했다.
