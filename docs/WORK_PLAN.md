# 배포형 운영 플랫폼 구현 작업계획서

> 기준 설계: `docs/design/DESIGN.md` v0.1
> 상태: 제안·검토중
> 담당: Project Main 단일 writer
> 작업 규칙: 최신 `origin/main`에서 `codex/` branch와 `.worktree/`를 하나만 사용하고, checkpoint마다 commit·push한다. PR로만 main에 병합한다.

## 1. 목표와 범위

설계서의 Endpoint, API 키·tenant, Provider catalog, N:N routing, 분석·비용·모니터링을 구현한다. 설치형 CLI의 개인 실행 동작은 유지한다. Oracle/운영 배포는 개발 계획과 분리한다.

## 2. 단계 지도

| 단계 | 산출물 | 의존성 |
| --- | --- | --- |
| S0 계약 고정 | API·scope·Provider catalog·라우팅 결정 | DESIGN 승인 |
| S1 저장 모델·migration | Provider/Model/Routing/Key/usage/cost/audit schema | S0 |
| S2 Endpoint 인증 | OpenAI·Anthropic ingress, key·tenant·scope | S1 |
| S3 Provider catalog | 분석/LLM 선택형 등록과 Secret 참조 | S1 |
| S4 Routing engine | N:N binding, priority, fallback, fail-closed | S1·S3 |
| S5 운영 기능 | usage, pricing, budget, analytics, monitoring, audit | S2·S4 |
| S6 Console UX | Endpoint·키·Provider·Routing·Costs·Monitoring 화면 | S2~S5 |
| S7 통합 검증 | WSL 정식 DB·Provider sandbox·브라우저·OmniRoute 검증 | S1~S6 |

## 3. 단계별 상세 계획

### S0: 계약 고정

**설계 추적:** D-Endpoint, D-Credential, D-Provider, D-Routing, D-Operations

**수정 대상:** `docs/design/DESIGN.md`, `docs/WORK_PLAN.md`, `docs/WORK_STATUS.md`

**RED:** OpenAI/Anthropic 요청 예시, tenant 없는 요청, 폐기 key, 분석 Provider 실패, fallback 후보 없음 시나리오를 계약 테스트 fixture로 고정한다.

**GREEN:** 경로·헤더·scope·오류 코드·민감정보 비저장 규칙이 문서와 fixture에서 일치한다.

**완료 조건:** 신산님이 공개 계약, N:N routing, API key 보안, 비용·보존 경계를 승인한다.

### S1: 저장 모델과 migration

**파일:**
- Create: `migrations/versions/0004_managed_platform.py`
- Modify: `media_bridge_control/models.py`, `media_bridge_control/schemas.py`, `media_bridge_control/db.py`, `media_bridge_control/snapshots.py`
- Test: `tests/integration/test_managed_schema.py`, `tests/unit/test_secret_redaction.py`

**산출물:** provider catalog/provider/model/routing binding, service account/credential, usage/cost/budget/audit 모델과 인덱스. 키 원문은 저장하지 않고 digest·selector만 저장한다.

**RED:** duplicate binding, 다른 tenant 접근, 폐기 credential 재사용, snapshot에 secret 원문 포함 시 실패한다.

**GREEN:** upgrade·downgrade, tenant isolation, signed snapshot round-trip, redaction 테스트가 통과한다.

### S2: Endpoint와 인증

**파일:**
- Modify: `media_bridge_gateway/`, `media_bridge_control/api.py`, `media_bridge_control/credentials.py`, `media_bridge_control/security.py`
- Create: `tests/integration/test_openai_compatible_ingress.py`, `tests/integration/test_anthropic_compatible_ingress.py`

**산출물:** `/v1/models`, `/v1/responses`, `/v1/chat/completions`와 Anthropic 호환 변환, key·tenant·scope 검증, bounded safe error.

**RED:** bearer 누락/중복, tenant 누락, cookie 인증, unknown model, expired/revoked key, oversized body가 downstream 0회인지 고정한다.

**GREEN:** text JSON·SSE, model 목록, OpenAI/Anthropic 최소 요청, 실패 시 안전 오류가 통과한다.

### S3: Provider catalog와 선택형 등록

**파일:**
- Create: `media_bridge_control/provider_catalog.py`, `media_bridge_control/provider_registry.py`
- Modify: `media_bridge_control/api.py`, `media_bridge_control/secrets.py`
- Web: `web/src/operations/ProvidersPage.tsx`, `web/src/onboarding/ProviderStep.tsx`, `web/src/app/router.tsx`
- Test: `tests/unit/test_provider_catalog.py`, `web/src/operations/Operations.test.tsx`

**산출물:** 분석 Provider와 Non-Vision LLM Provider 카탈로그, endpoint/protocol/model/capability 자동 채움, API 키·Secret 참조 입력, 연결 시험, 고급 호환 endpoint 등록.

**RED:** 임의 endpoint만 입력하고 catalog 없이 활성화, secret 원문 응답, kind가 분석/LLM과 불일치한 저장을 실패시킨다.

**GREEN:** Provider 선택 → 필요한 키만 입력 → 연결 시험 → enabled 전환과 Provider 없이 콘솔 이동 흐름이 통과한다.

### S4: N:N routing engine

**파일:**
- Create: `media_bridge_gateway/routing_profiles.py`, `media_bridge_gateway/provider_selection.py`
- Modify: `media_bridge_gateway/router.py`, `media_bridge_gateway/gateway.py`, `media_bridge_control/api.py`
- Test: `tests/unit/test_provider_selection.py`, `tests/integration/test_routing_profiles.py`

**산출물:** media type/model/tenant/cost/priority/fallback 조건을 포함한 routing profile과 binding. 분석 성공 후 Non-Vision LLM을 선택하며 미디어·정책 실패 시 호출하지 않는다.

**RED:** inactive provider, cycle, duplicate priority, capability 불일치, 모든 fallback 실패에서 downstream 0회 또는 bounded error를 확인한다.

**GREEN:** 1:1·N:N 조합, 기본 대상, fallback, health/예산 제한, OmniRoute target 선택이 통과한다.

### S5: 분석·비용·모니터링

**파일:**
- Create: `media_bridge_control/usage.py`, `media_bridge_control/costs.py`, `media_bridge_control/monitoring.py`
- Modify: `media_bridge_control/audit.py`, `media_bridge_gateway/`
- Test: `tests/integration/test_usage_cost_budget.py`, `tests/integration/test_operational_events.py`

**산출물:** usage/cost event, pricing, budget hard limit, provider utilization, activity/log/timeline/audit projection. 원문 요청·media·key는 집계에서 제외한다.

**RED:** 예산 초과 우회, tenant 간 집계 노출, secret/body 로그 기록을 실패시킨다.

**GREEN:** 성공·차단·실패·latency·token/size bucket 집계, 가격 계산, 예산 차단, 감사 조회가 통과한다.

### S6: 운영 Console UX

**파일:**
- Create: `web/src/operations/EndpointPage.tsx`, `web/src/operations/CredentialsPage.tsx`, `web/src/operations/RoutingProfilesPage.tsx`, `web/src/operations/CostsPage.tsx`, `web/src/operations/MonitoringPage.tsx`
- Modify: `web/src/app/router.tsx`, `web/src/styles/global.css`, `web/src/operations/ProvidersPage.tsx`
- Test: `web/src/operations/ManagedPlatform.test.tsx`, `tests/e2e/test_console_managed_platform.py`

**산출물:** Endpoint 복사/호환성 안내, key 발급·폐기, Provider 선택, N:N routing 편집, costs·analytics·monitoring·audit 화면과 empty/loading/error/read-only 상태.

**RED:** 1440px에서 overflow, 430px에서 입력 가림, 키 재노출, 권한 없는 action, Provider 빈 입력 강제가 재현되어야 한다.

**GREEN:** 1920×1080·1440×900·430×844에서 키보드·focus·label·status·오류 흐름을 실제 browser로 검증한다.

### S7: 통합 검증

**수정 대상:** `docs/WORK_STATUS.md`, `docs/DEVELOPMENT_ENVIRONMENT.md`, `docs/manuals/`, 배포 계획 문서

**검증:**

- 로컬 unit/typecheck/lint/build
- WSL-server 정식 PostgreSQL migration과 통합 테스트
- Provider sandbox 또는 승인된 실제 연결 시험
- 실제 OmniRoute에 배포형 HTTPS Endpoint와 service key를 등록한 최소 text 요청
- OpenAI·Anthropic 브라우저/API smoke
- 비용·모니터링·감사 화면 browser test

**완료 조건:** 필수 테스트·typecheck·lint·build·브라우저·DB·Provider·OmniRoute 검증이 모두 통과하고, 미검증 범위를 문서에 명시한다.

## 4. 통합·branch·checkpoint

각 Stage는 RED 테스트 → 최소 구현 → GREEN → 해당 범위 검증 → commit → SSH alias push 순서로 진행한다. branch는 최신 `origin/main`에서 하나만 만들고 `.worktree`에서 checkout한다. PR은 정확한 검증 commit으로만 생성하며, main 병합 후 merged-main smoke와 branch/worktree 삭제를 수행한다.

## 5. 위험·rollback·승인 경계

- 공개 Endpoint·API 계약 변경: 설계 승인 필요. rollback은 이전 snapshot과 이전 image로 되돌린다.
- DB schema/migration·persistent data: 별도 승인과 backup/restore 검증 필요.
- 인증·권한·Secret: 원문 노출 없이 security review와 폐기 검증 필요.
- 실제 Provider 비용·OmniRoute 운영 연결: sandbox 우선, 운영 호출은 별도 승인.
- Anthropic 변환·tenant header 계약이 확정되지 않으면 S2/S7 완료로 판정하지 않는다.

## 6. 계획 변경 이력

| 일시 | 변경 | 이유 | 승인 |
| --- | --- | --- | --- |
| 2026-09-18 | 초안 작성 | 설치형과 차별되는 배포형 운영 범위 확정 | 검토중 |

