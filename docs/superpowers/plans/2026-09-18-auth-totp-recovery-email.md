# 배포형 관리자 인증앱·복구 이메일 2단계 인증 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 배포형 Control Plane/Web에 `admin/admin` 기본 계정과 TOTP 또는 복구 이메일 2단계 인증을 제공한다.

**Architecture:** 기존 배포형 `media_bridge_control` 인증·세션 경계를 확장해 TOTP 등록/검증과 복구 코드 발급/소비를 추가한다. Web은 기존 로그인/온보딩 라우팅을 단계형 인증 UI로 연결한다. 설치형 전용 모듈·문서·테스트는 변경하지 않는다.

**Tech Stack:** Python, SQLAlchemy, FastAPI 계층, pytest; React/TypeScript, Vitest.

**Spec:** `docs/superpowers/specs/2026-09-18-auth-totp-recovery-email-design.md`

## Global Constraints

- 배포형 Control Plane/Web만 수정한다.
- 기본 계정은 `admin/admin`이며 삭제 불가다.
- 비밀번호 변경 기능을 추가하지 않는다.
- TOTP secret·복구 코드·SMTP 비밀값을 평문 저장·로그 기록하지 않는다.
- 설치형 Media Bridge의 코드·문서·테스트는 수정하지 않는다.
- 각 작업은 failing test → minimal implementation → focused test → checkpoint commit 순서로 진행한다.

### Task 1: 배포형 인증 데이터 모델과 TOTP 단위 계약

**Files:**
- Modify: `media_bridge_control/models.py`
- Modify: `media_bridge_control/bootstrap.py`
- Create/Modify: `tests/control/test_bootstrap.py` 또는 현재 인증 서비스 단위 테스트 위치

**Interfaces:**
- Produces `ensure_default_admin()`, `begin_totp_enrollment()`, `confirm_totp_enrollment()`, `verify_totp()` 서비스 동작.

- [ ] 기본 admin 자동 보장과 삭제·비활성화·비밀번호 변경 거부 테스트를 먼저 추가한다.
- [ ] TOTP 미등록/등록 상태와 잘못된 코드 테스트를 추가하고 실패를 확인한다.
- [ ] SQLAlchemy 모델과 서비스 구현을 추가해 테스트를 통과시킨다.
- [ ] 관련 Python 테스트를 실행하고 commit한다.

### Task 2: 2단계 로그인 및 복구 이메일 API

**Files:**
- Modify: `media_bridge_control/api.py`
- Modify: `media_bridge_control/bootstrap.py`
- Modify: `media_bridge_control/config.py` 또는 실제 배포형 설정 모듈
- Modify: `tests/control/test_api.py` 및 SMTP/복구 관련 테스트 위치

**Interfaces:**
- Login API returns a pending second-factor state before issuing a session.
- TOTP enrollment and recovery endpoints consume the service contracts from Task 1.

- [ ] 자격 증명 성공 후 세션을 즉시 발급하지 않는 API 테스트를 추가한다.
- [ ] TOTP 검증, 복구 이메일 요청, 복구 코드 소비, 만료·일회성·rate limit 테스트를 추가하고 실패를 확인한다.
- [ ] SMTP 설정 주입과 비밀값 비노출 오류를 구현한다.
- [ ] API 회귀 테스트와 Python lint/typecheck를 실행하고 commit한다.

### Task 3: 배포형 Web 인증 화면

**Files:**
- Modify: `web/src/auth/AuthProvider.tsx`
- Modify: `web/src/app/router.tsx`
- Modify: `web/src/onboarding/SetupLoginStep.tsx` 및 실제 로그인 화면
- Create/Modify: `web/src/auth/*test.tsx`, 관련 API contract/client 파일

**Interfaces:**
- Consumes login pending states and TOTP/recovery API responses from Task 2.
- Produces accessible login, enrollment, TOTP verification, and recovery flows.

- [ ] 로그인 → TOTP 등록/검증 → 복구 이메일 전환의 웹 테스트를 먼저 추가한다.
- [ ] bootstrap token 입력과 사용자 비밀번호 설정 UI를 배포형 기본 흐름에서 제거한다.
- [ ] 화면·라우팅·API client를 구현하고 Vitest를 통과시킨다.
- [ ] 웹 lint/typecheck/build/test를 실행하고 commit한다.

### Task 4: 통합 검증과 운영 문서

**Files:**
- Modify: 배포형 설치/운영 문서의 인증 섹션
- Modify: `docs/work-status/media-bridge.md`가 존재하는 경우
- Test: 전체 Python/Web 검증 명령

- [ ] 배포형 로그인·초기 TOTP 등록·복구 코드 흐름을 통합 테스트한다.
- [ ] 설치형 문서와 파일이 변경되지 않았는지 확인한다.
- [ ] 전체 테스트·lint·typecheck·build를 실행한다.
- [ ] 검증 결과와 미검증 범위를 기록하고 최종 checkpoint를 push한다.
