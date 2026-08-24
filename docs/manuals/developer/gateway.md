# Media Bridge Gateway 개발자 계약

## 현재 판정

P3 Gateway 코드는 `P3_CODE_READY_LIVE_DOWNSTREAM_NOT_VERIFIED`다. loopback TCP에서
인증된 Responses JSON/SSE와 Streamable HTTP MCP를 검증했지만 실제 OCR·Vision·Solar
provider, OpenCodex, OmniRoute, 운영 HTTPS 배포는 검증하지 않았다.

## 강제 처리 순서

`POST /v1/responses`는 다음 순서를 서버에서 강제한다.

1. signed snapshot 파일의 원자 교체를 확인하고, 유효하면 새 generation을 적용한다.
   위조·손상 snapshot이면 last-known-good generation을 유지한 뒤 요청 generation을 고정한다.
2. Data Plane credential의 digest, scope, 만료, 폐기 상태를 검증한다.
3. OpenAI Responses 입력을 제한된 계약으로 normalize한다.
4. 실제 선택된 `model`의 exact·active capability를 snapshot registry에서 확인한다.
5. media가 있고 대상이 Non-Vision이면 같은 generation의 Core
   `prepare_for_model`로 OCR·Vision·sanitizer·cleanup을 수행한다.
6. 성공한 payload만 다시 만들고 요청별 nonce를 포함한 input/output digest와 receipt로
   봉인한다.
7. generic Responses downstream이 socket write 직전에 receipt, digest, target,
   capability, action, media reference를 재검증한다.
8. downstream 성공 뒤에만 후속 요청용 sanitized state를 기록한다. state 기록만 실패한
   경우 이미 받은 provider 응답은 보존하고 `Media-Bridge-State: unavailable` 경고를 붙인다.

unknown/stale capability, 인증, normalize, acquisition, OCR, Vision, sanitizer, cleanup,
seal 검증 중 하나라도 실패하면 downstream 호출은 0회다. Non-Vision 요청에서는 원본
media, base64, URL, asset/local-path reference를 downstream payload에 남기지 않는다.

## HTTP 표면

| 경로 | 메서드 | 필요한 scope | 계약 |
|---|---|---|---|
| `/v1/responses` | `POST` | `responses:invoke` | JSON 또는 downstream SSE 응답 |
| `/assets` | `POST` | `assets:write` | tenant-scoped 임시 asset 발급 |
| `/mcp` | MCP Streamable HTTP | `mcp:invoke` | 3개 Core 도구 |

모든 알려진 경로는 `Authorization: Bearer <credential>`을 요구한다. Admin session cookie는
Data Plane 인증 수단이 아니며 cookie가 있으면 거부한다. 중복 Authorization/Cookie 헤더도
거부한다. 알려지지 않은 경로는 MCP로 재해석하지 않고 bounded 404를 반환하며 trailing
slash redirect는 허용하지 않는다. 기본 Responses body 상한은 4 MiB, asset upload 상한은
2 MiB다.

credential 원문 형식은 P1이 한 번만 발급하는 `mbc_<selector>.<secret>`이며 snapshot에는
selector, HMAC digest, scopes, expiry, revoked 정보만 들어간다. 원문은 DB, snapshot,
설정 파일, 운영 이벤트에 저장하지 않는다.

## Responses 입력과 후속 상태

- `model`은 registry의 exact ID여야 한다.
- 문자열 input 또는 제한된 user message/content만 허용한다.
- image/PDF는 검증된 data URI 또는 tenant asset 경계를 통해 획득한다.
- Vision passthrough도 exact active capability와 PDF verified flag를 요구한다.
- `previous_response_id`는 Gateway가 성공 뒤 저장한 같은 credential·tenant의 sanitized
  state만 참조한다. 변환이 끝나 원본 media/reference가 0개인 state는 media-tainted가
  아니며, 이미지가 있던 원대화 전체를 복원하지 않는다.
- state에는 sanitized user text, media taint/modality, credential selector, target,
  snapshot version, TTL만 저장한다. assistant, reasoning, tool result, raw provider response,
  원본 media는 저장하지 않는다.
- 실패 transaction은 state를 만들지 않으므로 새 text 요청을 같은 세션에서 계속할 수
  있다.

## 안전한 오류와 운영 이벤트

오류 응답은 bounded safe code/message만 반환하며 provider body나 credential을 반사하지
않는다. Gateway 운영 이벤트는 다음 필드만 허용한다.

- 내부 request ID
- route event type
- Core가 검증한 model ID 또는 `null`
- snapshot/policy version
- 결과 code
- latency bucket과 request-size bucket

요청 본문, media, OCR·Vision text, Secret, credential, response body 필드는 이벤트 계약에
없다. 현재 기본 sink는 no-op이며 P1 `OperationalEventWriter`와의 persistence adapter 및
배포 연결은 후속 통합 범위다.

## 실행 진입점과 Secret 경계

설치 package는 `media-bridge-gateway` console script를 제공한다. 실제 프로세스 실행에는
다음 설정이 필요하며 Secret 원문은 환경변수 또는 대응하는 `*_FILE`로만 주입한다.

- snapshot: `MEDIA_BRIDGE_SNAPSHOT_PATH`, `MEDIA_BRIDGE_SNAPSHOT_KEY_ID`,
  `MEDIA_BRIDGE_SNAPSHOT_PUBLIC_KEY` 또는 `_FILE`
- Data Plane: `MEDIA_BRIDGE_GATEWAY_AUTH_PEPPER` 또는 `_FILE`,
  `MEDIA_BRIDGE_RECEIPT_SECRET` 또는 `_FILE`, `MEDIA_BRIDGE_ASSET_ROOT`
- OCR: `MEDIA_BRIDGE_OCR_ENDPOINT`, `MEDIA_BRIDGE_OCR_API_KEY` 또는 `_FILE`
- Vision: `MEDIA_BRIDGE_VISION_ENDPOINT`, `MEDIA_BRIDGE_VISION_MODEL`,
  `MEDIA_BRIDGE_VISION_API_KEY` 또는 `_FILE`
- downstream: `MEDIA_BRIDGE_DOWNSTREAM_RESPONSES_URL`,
  `MEDIA_BRIDGE_DOWNSTREAM_API_KEY` 또는 `_FILE`
- optional Solar analysis: `MEDIA_BRIDGE_SOLAR_ENDPOINT`, `MEDIA_BRIDGE_SOLAR_MODEL`,
  `MEDIA_BRIDGE_SOLAR_API_KEY` 또는 `_FILE`
- listener: `MEDIA_BRIDGE_GATEWAY_HOST` 기본 `127.0.0.1`,
  `MEDIA_BRIDGE_GATEWAY_PORT` 기본 `8001`

snapshot, asset root는 absolute non-symlink path여야 한다. downstream URL은 HTTPS 또는
loopback HTTP의 정확한 `/v1/responses` 경로만 허용하고 redirect와 proxy environment를
사용하지 않는다. 이번 P3에서는 process 실행·port 개방·reverse proxy·배포를 하지 않았다.

downstream JSON은 bounded body로 검증하고, SSE는 첫 유효 response ID를 확인한 뒤 전체
응답을 메모리에 모으지 않고 점진적으로 전달한다. timeout·transport·size 오류는 안전한
bounded 오류로 변환하며 provider body를 반사하지 않는다.

## 검증된 범위

- 실제 loopback TCP Responses JSON/SSE
- 실제 Streamable HTTP MCP `initialize → tools/list → tools/call`
- body limit과 no-redirect
- 동일 payload의 요청별 nonce·receipt 분리, 동일 receipt replay 2회째 차단과 network call 1회
- snapshot 원자 reload·credential revoke 즉시 반영·invalid snapshot LKG 유지
- 실제 TCP SSE 첫 event의 완료 전 점진 전달
- Non-Vision media/reference 0과 failure matrix downstream call 0
- 변환된 후속 state의 media-taint 제거와 state persistence 실패 시 응답 보존
- Vision image/PDF exact capability 경계
- credential/scope/rate-limit/snapshot generation/shared state isolation
- unknown route 404와 duplicate Authorization/Cookie 차단
- 기존 OmniRoute 명칭 wrapper 회귀

실제 provider 비용 호출, 다른 PC HTTPS, OpenCodex·OmniRoute adapter E2E와 운영 다중
process rate-limit/event sink는 아직 검증하지 않았다.
