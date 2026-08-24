# Media Bridge Web Console 시작하기

> 현재 제공 범위: `P2B_CODE_READY_LIVE_DOWNSTREAM_REMOTE_BROWSER_NOT_VERIFIED`

이 문서는 현재 구현·검증된 Web Console 화면만 설명한다. 설치 패키지와 다른 PC의 운영 HTTPS 접속은 아직 제공·검증되지 않았다.

## Web Console이 하는 일

Web Console은 Media Bridge의 Provider 참조, 모델 capability, fail-closed 정책과 signed snapshot 상태를 관리한다. Secret 원문은 Provider 설정에 저장하지 않고 환경변수 같은 외부 Secret 참조만 등록한다.

## 최초 설정

운영자가 Control Plane과 Web Console을 같은 HTTPS origin으로 준비한 뒤 `/setup`을 연다.

1. **시스템 확인**: 실제 `/admin/v1/health` 상태를 확인한다.
2. **최초 관리자**: 운영자가 별도 경로로 전달한 15분 일회용 bootstrap token, 관리자 이름과 12자 이상 비밀번호를 입력한다.
3. **복구 코드**: 한 번만 표시되는 recovery code를 안전한 Secret 저장소에 보관하고 창을 닫는다.
4. **관리자 재로그인**: 비밀번호를 다시 입력한다. 복구 코드를 보여 주는 동안 비밀번호를 브라우저에 유지하지 않기 위한 단계다.
5. **Provider**: 이름, HTTPS endpoint, Secret 환경변수 이름을 입력한다. API key 원문을 입력하지 않는다.
6. **Model**: 정확한 model ID와 capability 근거를 입력한다. 현재 온보딩은 Non-Vision text model을 등록한다.
7. **Policy**: 기본 fail-closed 정책을 생성한다.
8. **접근 credential**: client credential을 한 번 발급하고 즉시 안전한 Secret 저장소에 보관한다. 이 값의 발급은 연결 상태를 뜻하지 않는다.
9. **검증과 발행**: draft 검증이 성공한 경우에만 첫 signed snapshot을 발행한다.

새로고침한 경우 진행 상태는 P1에 실제 저장된 Provider·Model·Policy·credential·snapshot 목록으로 다시 판정한다. 입력 중이던 Secret이나 본문을 browser storage에 저장해 재개하지 않는다.

## 역할별 화면

- `admin`: 모든 조회 화면, client credential, snapshot 발행·rollback을 사용할 수 있다.
- `operator`: Provider·Model·Policy 조회와 허용된 변경을 수행할 수 있다. 사용자·credential·snapshot 관리 API는 허용되지 않는다.
- `viewer`: Provider·Model·Policy·Audit·System을 읽기만 할 수 있다.

Connections는 admin/operator/viewer가 조회할 수 있다. admin만 추가·폐기할 수 있고,
admin/operator만 연결 시험을 실행할 수 있다. Test Lab은 admin/operator만 사용할 수 있다.

화면에서 작업을 숨기는 것과 별개로 실제 허용·거부는 Admin API가 401/403으로 강제한다.

## Connections와 Test Lab

Connections에는 Gateway HTTPS URL과 credential의 외부 Secret 참조를 등록한다. credential 원문은
입력하거나 저장하지 않는다. `연결 시험`은 Gateway 상태를 확인하며, 성공한 경우에만 마지막 정상
시각을 갱신한다. client credential 발급과 Connection 정상 상태는 서로 다른 개념이다.

Test Lab에서 Connection, 정확한 대상 model ID, 변환 profile, 요청과 이미지/PDF를 선택할 수 있다.

- `Preview`: Gateway의 전처리만 수행하며 downstream Provider 호출은 0회다.
- `실제 downstream 시험`: 비용 발생 안내 checkbox를 해당 요청에 새로 선택해야만 실행된다.
- 입력 media·요청과 결과는 browser storage에 저장하지 않으며 실행 시작, 수동 삭제, 화면 이탈 또는
  10분 TTL 뒤 제거된다.
- 화면은 same-origin `/admin/v1`만 호출한다. Gateway `/assets`나 `/v1/*`를 브라우저에서 직접
  호출하지 않는다.

## 안전 수칙

- bootstrap token, 비밀번호, recovery code, client credential을 URL이나 일반 메모에 넣지 않는다.
- Provider API key 원문 대신 승인된 Secret 참조만 사용한다.
- one-time dialog를 닫기 전에 Secret 저장소 보관 여부를 확인한다.
- capability 근거와 만료일이 정확하지 않으면 모델을 안전하다고 가정하지 않는다.
- snapshot 발행 또는 rollback 전 대상을 다시 확인한다.

## 아직 검증되지 않은 범위

- 다른 PC에서의 실제 HTTPS 접속과 운영 reverse proxy·인증서.
- 실제 OCR·Vision·Solar provider 호출과 비용.
- 실제 OCR·Vision·Solar provider와 비용이 발생하는 live Gateway downstream.
- Docker Compose 설치, backup/restore, upgrade/rollback.
- OpenCodex·OmniRoute 실제 adapter 연결.

이 항목은 현재 화면이나 테스트 통과로 완료된 것으로 간주하지 않는다.
