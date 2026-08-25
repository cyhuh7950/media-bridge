# Adapter 운영자 가이드

## Secret 경계

- Adapter credential과 decision HMAC 원문은 환경변수 또는 외부 Secret으로만 주입한다.
- config, manifest, DB, snapshot, 로그에는 환경변수 이름만 둔다.
- OmniRoute critical plugin은 다음 세 이름만 child에 요청한다.
  - `MEDIA_BRIDGE_ADAPTER_ENDPOINT`
  - `MEDIA_BRIDGE_ADAPTER_CREDENTIAL`
  - `MEDIA_BRIDGE_ADAPTER_DECISION_HMAC`
- undeclared 환경변수는 child로 전달되지 않는다. 필수 값 누락은 plugin 시작 전에 차단한다.

## Preview 생성

```bash
media-bridge-adapter render-config \
  --adapter omniroute \
  --external-version 3.8.50 \
  --external-base-commit f95b03d70929a6a850d4b986a7bbad6740dd02e0 \
  --extension-commit eaa5ba08579f93db2d3e5b0046792ce8f70fb208 \
  --endpoint https://media-bridge.example/adapter/v1/pre-upstream \
  --credential-env MEDIA_BRIDGE_ADAPTER_CREDENTIAL \
  --decision-hmac-env MEDIA_BRIDGE_ADAPTER_DECISION_HMAC \
  --output /absolute/new/path/omniroute-preview.json
```

출력은 자동 설치 파일이 아닌 검토용 fragment다. 기존 파일은 덮어쓰지 않으며 bundled plugin의
경로와 integrity를 함께 기록한다. 실제 설치·서비스 등록·포트·proxy 변경은 P4 범위가 아니다.

## 연결 시험

`media-bridge-adapter test-connection`은 문서화된 Adapter endpoint에 text-only probe 한 번만
전송하고 redirect를 따르지 않는다. credential은 지정한 환경변수에서 읽으며 출력·오류에 표시하지
않는다. 이 시험은 Adapter 도달성을 확인할 뿐 실제 provider 호출 성공을 의미하지 않는다.

## 제거와 장애

Adapter registry 제거는 generic MCP/Gateway와 sealed downstream을 제거하지 않는다. critical plugin을
운영에서 제거할 때는 먼저 해당 router 경로를 중지하고 명시적으로 deactivate/uninstall해야 한다.
Control Plane 중단과 provider live fallback은 P4에서 검증하지 않았다.
