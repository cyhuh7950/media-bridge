# Media Bridge 작업현황

판정: RUNNING
정본: `docs/design/DESIGN.md`, `docs/WORK_PLAN.md`, 현재 worktree `D:/Project/Media-Bridge/.worktree/auth-totp-recovery-email`
작업계획: S3 Provider catalog — 카탈로그·관리 API·DB 스키마·Console 선택 UI·N:N routing 연결 완료, 운영 통합 검증은 다음 작업
Git: `codex/auth-totp-recovery-email` / checkpoint push 예정 / 기존 `.pr-body.md` untracked 보존 / 단일 writer 어울
최근 완료 증거: TOTP QR·Provider 선택 우회 흐름의 기존 구현과 배포형 Control Plane 문서를 확인함. 2026-09-19 OmniRoute 공급자 화면에서 API 키 호환 1/1, API 키 Provider 5/230, Image Providers 0/8, Local Providers 0/14 및 OpenAI/Anthropic 호환 추가 기능을 확인함.
현재 변경: Provider catalog, Provider schema/migration, onboarding/operations 선택 UI, N:N routing profile API·UI, fail-closed Provider selection primitive와 `/v1/models` runtime endpoint 구현 완료. 기존 `.pr-body.md`는 삭제하지 않음.
실행·검증 결과: control/gateway unit·packaging 79 passed, web lint 0 errors, web tests 27 passed, web build·ruff·compileall·git diff --check 통과. snapshot model discovery 회귀 포함 관련 63 passed. WSL-server disposable PostgreSQL에서 migration/connection 4 passed, configuration API 2 passed. Provider selection의 실제 downstream 다중 endpoint wiring·DB 등록·배포 검증은 미실행.
오류와 조치: 없음.
미검증·승인 경계: 공개 OpenAI/Anthropic 계약, API key·tenant, DB migration, N:N routing, 비용·모니터링, OmniRoute 배포형 연결은 설계 승인 전 미구현·미검증. 인증·권한·Secret·비용·지속 schema 변경은 별도 승인 대상.
정확한 다음 조치: Provider selection을 Gateway transaction/downstream에 연결하고, WSL-server에서 routing profile 통합 테스트와 Provider sandbox를 실행한다.

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
