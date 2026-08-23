# Media Bridge Web Console 시작하기

> 현재 제공 범위: `P2A_CODE_READY_REMOTE_BROWSER_NOT_VERIFIED`

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

화면에서 작업을 숨기는 것과 별개로 실제 허용·거부는 Admin API가 401/403으로 강제한다.

## 현재 사용할 수 없는 화면

Connections와 Test Lab은 `DEPENDENCY_NOT_READY`를 표시한다.

- connection 저장, 연결 시험, 마지막 정상 시각, 연결 폐기는 아직 없다.
- 미디어 업로드, preview, OCR 본문, downstream 시험 호출은 아직 없다.
- client credential을 만들었다고 연결된 것으로 표시하지 않는다.

이 기능들은 P3 Gateway의 API·보존·RBAC 계약이 검증된 뒤 P2b에서 활성화한다.

## 안전 수칙

- bootstrap token, 비밀번호, recovery code, client credential을 URL이나 일반 메모에 넣지 않는다.
- Provider API key 원문 대신 승인된 Secret 참조만 사용한다.
- one-time dialog를 닫기 전에 Secret 저장소 보관 여부를 확인한다.
- capability 근거와 만료일이 정확하지 않으면 모델을 안전하다고 가정하지 않는다.
- snapshot 발행 또는 rollback 전 대상을 다시 확인한다.

## 아직 검증되지 않은 범위

- 다른 PC에서의 실제 HTTPS 접속과 운영 reverse proxy·인증서.
- 실제 OCR·Vision·Solar provider 호출과 비용.
- Connections·Test Lab 및 실제 Gateway downstream.
- Docker Compose 설치, backup/restore, upgrade/rollback.
- OpenCodex·OmniRoute 실제 adapter 연결.

이 항목은 현재 화면이나 테스트 통과로 완료된 것으로 간주하지 않는다.
