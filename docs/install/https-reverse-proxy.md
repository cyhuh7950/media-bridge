# Media Bridge HTTPS reverse proxy 경계

Admin API는 HTTPS scheme, exact Host, same Origin을 강제한다. `deploy/compose.https-example.yaml`은
자동 적용하지 않는 profile 예시이며 proxy image digest, certificate, config를 운영자가 명시해야 한다.
proxy는 request body log를 끄고 `X-Forwarded-Proto=https`를 신뢰할 source를 좁힌다. Control은 공개
관리망, Data는 필요한 client 경로만 허용하고 DB는 노출하지 않는다. 다른 PC HTTPS browser 시험은
`REMOTE_HTTPS_BROWSER_NOT_VERIFIED`다.
