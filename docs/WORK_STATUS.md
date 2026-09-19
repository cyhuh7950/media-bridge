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
