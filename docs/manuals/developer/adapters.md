# Adapter 개발자 계약

Adapter HTTP 경계는 `POST /adapter/v1/pre-upstream`이며
`media-bridge-pre-upstream/v1` request/result만 받는다. 외부 router는 최종 provider/model을
선택한 뒤 이 경계를 호출하고, 반환된 target·digest·HMAC·media-removal 조건을 검증한 후에만
provider transport를 실행한다.

## 강제 순서

1. router가 실제 provider/model을 확정한다.
2. Adapter가 canonical request를 Gateway `/v1/prepare`로 변환한다.
3. Gateway가 capability와 media를 판정하고 변환·sanitizer·cleanup을 수행한다.
4. 외부 extension 또는 plugin이 target echo, input/output digest, HMAC과 잔존 media를 검증한다.
5. 성공한 body만 provider에 전달한다. 오류·timeout·unknown build는 provider 호출 0회다.

Adapter SDK는 Core·Control DB를 import하지 않는다. legacy sealed OmniRoute downstream은
한 릴리스 동안 `media_bridge.omniroute_adapter`에서 새 package로 re-export한다.

## 호환성 조회

```bash
media-bridge-adapter inspect \
  --adapter opencodex \
  --external-version 2.28.0 \
  --external-base-commit 5840591322117f3ee9568b35b135a6d4339f7711 \
  --extension-commit fbd539bc1a68a4a9ce85823096daa537a67ec742
```

설정 생성은 preview-only이며 명시한 신규 파일만 생성한다. 기존 파일은 덮어쓰지 않는다.
OmniRoute preview에는 bundled plugin asset 경로와 실제 source SHA-256 integrity가 포함된다.

## 검증 범위

OpenCodex extension과 OmniRoute extension은 격리 source에서만 검증됐다. 설치 binary나 실제
provider를 사용하지 않은 결과를 live E2E로 표시하면 안 된다.

## V2 책임 경계

`media-bridge-interop/v2`에서 Media Bridge는 asset 취득·변환·sanitizer·cleanup·provenance를
담당한다. Standalone은 자체 registry/downstream을 사용할 수 있지만 Eoul 연동에서는 Eoul이
capability·routing·Provider 실행을 소유한다. `V2_4_MEDIA_BRIDGE_CODE_READY`는 Eoul consumer
구현 완료를 뜻하지 않으며, Eoul 원본 변경과 consumer conformance는 별도 승인 범위다.

지원 명칭은 `Standard MCP/Gateway Integration`, `Deep Fail-closed Host Extension`,
`Standalone Downstream Adapter`로 분리한다. isolated OpenCodex·OmniRoute source extension은
일반 무수정 Adapter 또는 live 설치 지원으로 표시하지 않는다.
