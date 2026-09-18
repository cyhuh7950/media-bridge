# Media Bridge 배포형 운영 플랫폼 설계

> 상태: 제안·검토중
> 버전: 0.1
> 작성: 어울
> 기준: 신산님 요구사항 정리, 2026-09-18

## 1. 문제와 목표

설치형 Media Bridge는 한 PC에서 단일 사용자가 미디어를 분석하고 Non-Vision LLM으로 전달하는 개인 실행 환경이다. 배포형은 서버의 공용 Endpoint를 통해 여러 LLM·Agent·사용자가 호출하고, Provider·키·라우팅·비용·운영 상태를 중앙에서 관리해야 한다.

목표는 다음과 같다.

- 외부 클라이언트가 OpenAI 호환 또는 Anthropic 호환 Endpoint로 Media Bridge를 등록하고 호출한다.
- 사용자·클라이언트별 API 키, tenant, 권한, 만료와 폐기를 관리한다.
- 이미지·PDF 분석 Provider와 Non-Vision LLM Provider를 카탈로그에서 선택하고 필요한 키만 설정한다.
- 분석 Provider와 Non-Vision LLM Provider를 명시적인 라우팅 프로필로 N:N 연결한다.
- 요청·사용량·비용·Provider 상태·오류·감사 이벤트를 운영자가 확인한다.
- 미디어 검증·분석·정제에 실패하면 LLM 호출을 하지 않는 fail-closed 경계를 유지한다.

## 2. 비목표

- 설치형 CLI의 단일 사용자 lifecycle을 배포형 관리 화면으로 대체하지 않는다.
- Provider API 키 원문을 DB·로그·snapshot·브라우저 저장소에 보관하지 않는다.
- 모든 Provider를 자동으로 발견하거나 임의의 endpoint를 안전성 검증 없이 허용하지 않는다.
- embedding·reranker·음성·비디오 기능을 이 설계에서 자동 지원한다고 가정하지 않는다.
- 운영 배포·인증서·실제 외부 비용 호출은 개발 작업의 완료로 간주하지 않는다.

## 3. 역할과 권한

| 역할 | 권한 |
| --- | --- |
| 기본 관리자 `admin` | 삭제 불가. 시스템·사용자·Provider·라우팅·비용·감사 설정을 관리한다. 기본 비밀번호는 `admin`이며 변경 기능은 제공하지 않는다. 2단계 인증을 요구한다. |
| 운영 관리자 | Provider·모델·라우팅·비용·모니터링·키를 관리한다. 계정·보안 정책 변경은 제한할 수 있다. |
| 사용자/서비스 계정 | 자신에게 발급된 API 키와 허용된 tenant·모델·정책으로 Endpoint를 호출한다. |
| 조회자 | 대시보드·상태·통계·감사 결과를 읽지만 Secret·키 원문·변경 기능은 사용할 수 없다. |

## 4. 핵심 흐름

### 4.1 외부 요청

```text
LLM·Agent·OmniRoute
  -> HTTPS /v1/responses 또는 /v1/chat/completions
  -> API key·tenant 인증 및 권한 확인
  -> 모델·라우팅 프로필 선택
  -> media가 있으면 분석 Provider 선택·실행
  -> 원본 제거·정제된 텍스트 생성
  -> Non-Vision LLM Provider 선택·호출
  -> 호환 응답과 사용량·비용 이벤트 반환
```

Anthropic 호환 요청은 내부 정규화 후 동일한 미디어·라우팅 경계를 통과하고, 응답은 요청된 Anthropic 형식으로 반환한다. 알 수 없는 모델, 만료·폐기된 키, 비활성 Provider, 정책 위반, 분석 실패는 downstream 호출 0회로 종료한다.

### 4.2 Provider 연결

분석 Provider와 LLM Provider는 1:1 고정 연결이 아니라 **라우팅 프로필을 통한 N:N 연결**을 기본으로 한다.

```text
분석 Provider A ─┬─ LLM Provider A
분석 Provider B ─┼─ LLM Provider B
분석 Provider C ─┴─ OmniRoute
```

라우팅 프로필은 입력 미디어 유형, 모델 capability, tenant, 우선순위, 비용 상한, fallback 순서를 명시한다. 시스템은 프로필을 기준으로 자동 선택하되, 운영자가 승인하지 않은 조합을 임의로 만들지 않는다.

## 5. 기능 요구사항과 수용 기준

### Endpoint·호환성

- `GET /v1/models`로 활성 모델을 OpenAI 형식으로 제공한다.
- `POST /v1/responses`와 `POST /v1/chat/completions`를 제공한다.
- Anthropic 호환 경로와 요청·응답 변환 계약을 별도 명시한다.
- 운영 Endpoint는 HTTPS reverse proxy 뒤에 두며, 설치형 loopback 주소를 배포형 설정에 노출하지 않는다.
- OmniRoute에는 배포형 주소와 Media Bridge 서비스 키를 등록해 최소 text 요청을 성공시킨다.

### API 키·tenant

- 관리자가 사용자/서비스 계정별 키를 발급·폐기·만료시킬 수 있다.
- 원문은 발급 순간 한 번만 반환하고 이후 selector·digest·scope·tenant·상태만 저장한다.
- `Authorization: Bearer`와 tenant 경계를 검증한다. 중복 헤더·쿠키 인증·알 수 없는 tenant는 거부한다.
- scope는 최소 `models:read`, `responses:invoke`, `assets:write`로 분리한다.

### Provider 카탈로그

- 분석 Provider와 Non-Vision LLM Provider를 별도 유형으로 제공한다.
- 카탈로그에서 선택하면 endpoint·protocol·지원 capability·필수 Secret 환경변수 이름을 채운다.
- 사용자는 API 키 원문 또는 승인된 Secret 참조만 입력하며 Provider 이름과 endpoint를 임의로 입력하는 기본 흐름을 사용하지 않는다.
- 지원 목록 밖의 OpenAI 호환·Anthropic 호환 endpoint는 고급 등록에서 endpoint·protocol·모델 capability·Secret 참조를 명시하고 연결 시험을 통과해야 활성화한다.
- OmniRoute는 Non-Vision LLM Provider 후보로 등록할 수 있다. 이는 분석 Provider 등록과 분리한다.

### 라우팅·모델

- Provider, 모델, capability, tenant, 분석기 조합을 참조하는 라우팅 프로필을 생성·수정·비활성화한다.
- 기본 대상과 fallback 순서를 명시하고 health·quota·cost 정책에 따라 선택한다.
- `active` Provider와 모델만 발행된 snapshot에 포함한다.
- Vision-capable downstream으로 원본 media를 전달하는 경우와 Non-Vision 변환 경로를 명확히 구분한다.

### 분석·비용·모니터링

- 요청 수, 입력·출력 토큰, media 크기, latency, 성공·차단·실패, Provider별 사용량을 집계한다.
- Provider별 가격표와 모델별 단가를 관리하고 요청별 추정 비용과 기간별 확정 비용을 구분한다.
- tenant·사용자·Provider·모델별 예산과 hard limit을 지원한다. 한도를 넘으면 호출을 차단한다.
- 활동, 애플리케이션 로그, proxy 로그, console 로그, timeline, conversation, authorization/MCP/A2A 감사 이벤트를 민감정보 없이 제공한다.
- 운영 상태, runtime, 연결 복구력, Provider readiness를 별도로 표시한다.

## 6. 데이터 모델과 보존

핵심 엔터티는 `users`, `service_accounts`, `tenants`, `api_credentials`, `provider_catalog`, `providers`, `models`, `routing_profiles`, `routing_bindings`, `price_rules`, `budgets`, `usage_events`, `audit_events`, `snapshots`이다.

- `api_credentials`: selector, digest, scopes, tenant_id, expires_at, revoked_at, last_used_at만 저장한다.
- `providers`: kind(`analysis` 또는 `llm`), catalog_id, endpoint 참조, secret_ref, capability, status를 저장한다.
- `routing_bindings`: analysis_provider_id, llm_provider_id, media_type, model_id, priority, fallback_group, policy 조건을 저장한다.
- 요청 본문·media·API 키·provider 응답 원문은 운영 이벤트와 usage 집계에 저장하지 않는다.
- 원본 asset과 임시 변환물은 tenant 경계·TTL·명시적 삭제를 적용한다.
- 비용·사용량 이벤트는 재집계 가능한 request_id, tenant, provider, model, token/size/latency bucket을 보존한다.

## 7. 화면 정보구조

```text
Dashboard
├─ Endpoint
├─ API 키·사용자·Tenant
├─ Provider
│  ├─ 분석 Provider
│  ├─ Non-Vision LLM Provider
│  └─ 호환 endpoint 고급 등록
├─ Models
├─ Routing Profiles
├─ Policies
├─ Analytics / Usage / Provider Utilization
├─ Costs / Pricing / Budget
├─ Monitoring / Activity / Logs / Timeline / Conversations
├─ Audit
└─ System / Runtime / Connections / Test Lab
```

초기 설정은 관리자·2단계 인증·Endpoint 확인 뒤, Provider 선택과 키 설정을 기능별로 선택적으로 진행한다. Provider를 사용하지 않는 경우 콘솔로 이동할 수 있으며, 빈 endpoint·빈 Provider 이름을 먼저 입력하게 하지 않는다.

## 8. 보안·비기능 요구사항

- Secret은 환경변수·Docker Secret·외부 Secret Store 참조만 허용한다.
- API 키·Provider Secret·요청 본문·media·OCR/Vision 결과를 로그와 analytics에 기록하지 않는다.
- 모든 변경은 actor, 대상, 결과, request id를 감사 이벤트로 남긴다.
- 인증 실패·분석 실패·downstream 실패는 안전한 오류 코드만 반환한다.
- 1920×1080, 1440×900, 430×844에서 주요 관리 흐름을 검증한다.
- 키보드 focus, label, empty/loading/error/permission 상태와 4.5:1 본문 대비를 검증한다.
- Provider connection test, route preview, downstream 호출은 명시적 action으로 분리한다.

## 9. 미결정·승인 경계

- Anthropic 호환의 정확한 경로·streaming·tool 계약
- OmniRoute가 tenant 헤더를 전달하는 방식. 지원하지 않으면 Media Bridge 인증 adapter 또는 OmniRoute 쪽 custom header 설정이 필요하다.
- 가격표의 통화·반올림·외부 Provider별 실제 단가 갱신 주기
- 대화 보존 기간과 운영자 조회 범위
- Provider catalog의 1차 지원 목록과 실제 모델 ID
- persistent schema/migration, 인증·권한·Secret·비용 호출은 구현 전 별도 승인 대상이다.

## 10. 완료 기준

설계 완료는 이 문서의 요구사항과 미결정 경계를 신산님이 승인한 상태다. 제품 완료는 다음을 모두 충족해야 한다.

- OpenAI·Anthropic Endpoint의 실제 브라우저/API smoke
- 사용자별 키·tenant·scope·폐기 검증
- 분석 Provider → Non-Vision LLM N:N 라우팅과 fallback 검증
- OmniRoute 배포형 endpoint 연결 검증
- 비용·사용량·모니터링·감사 화면 검증
- PostgreSQL migration·snapshot·Secret 경계 검증
- 설치형 회귀 테스트와 배포형 통합·브라우저·Provider 검증
- 사용자·운영·연결·복구 매뉴얼 갱신

