# Media Bridge Adapter SDK

Adapter는 external router의 실제 선택 model 뒤 `POST /adapter/v1/pre-upstream`을 호출하고 target echo,
input/output digest, decision HMAC, media removal을 검증한다. timeout, duplicate Authorization, unknown/stale
capability, malformed result는 provider 호출 0회다. OpenCodex와 OmniRoute reference extension은 격리 source
fixture에서 검증됐으며 설치 원본에는 적용되지 않았다. 자세한 현재 계약은 `adapters.md`를 따른다.
