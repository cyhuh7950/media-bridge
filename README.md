# Non-Vision Media Bridge

이미지·PDF가 포함된 요청을 모델 호출 전에 판정하고, Non-Vision 모델에는 OCR·Vision 설명과
sanitizer를 통과한 텍스트만 전달하는 fail-closed MCP 제품입니다. Solar는 교체 가능한 텍스트
분석 backend 중 하나입니다.

핵심 안전 경계는 MCP 도구의 선택 호출이 아니라 `/v1/responses` ingress와 `RouterAdapter`입니다.

현재 브랜치에는 승인된 A안 ingress 코드가 구현돼 있지만 PCWSL Codex provider 설정과 배포는
수행하지 않았습니다. 실제 traffic이 Media Bridge를 통하도록 연결하고 직접 OmniRoute 접근을
차단하기 전에는 PCWSL 요청이 자동 보호된다고 간주하지 않습니다.

```text
OpenAI Responses request
  -> strict normalizer + tenant state isolation
  -> exact capability registry + PreRequestGate
      -> verified Vision: original media passthrough
      -> Non-Vision: acquire -> PDF rasterize -> OCR + Vision -> sanitize -> cleanup
      -> unknown/stale/failure: blocked
  -> sealed receipt + payload digest verification
  -> OmniRoute /v1/responses
```

## 제공 기능

- MCP 도구: `extract_image_context`, `analyze_error_image`, `prepare_for_model`
- 병행 transport: stdio, 인증된 Streamable HTTP `/mcp`
- 인증 업로드: `POST /assets` → tenant-scoped, one-shot `asset_id`
- 강제 ingress: 인증된 `POST /v1/responses` → gate 성공 후에만 OmniRoute 호출
- reference integration: mandatory `RouterAdapter`와 `GuardedDownstream`
- Responses 후속 상태: tenant-scoped TTL 30분, 최대 1,000개, sanitized text만 저장
- exact-ID capability registry와 만료 시각 기반 stale 차단
- PDF: PDFium 5.12.1로 144 DPI page PNG 변환 후 OCR·Vision 수행
- base64, asset, 제한적 local path, 기본 차단 URL 입력 경계
- HMAC gate receipt, 임시 workspace 삭제 확인, asset TTL·종료 시 정리

## 개발 환경 설치

Python 3.12에서 다음 순서로 재현합니다.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock
.venv/bin/pip install -e . --no-deps
```

## 필수 설정

값 자체는 설정 파일이나 명령 인자에 넣지 않습니다.

| 환경변수 | 의미 |
|---|---|
| `MEDIA_BRIDGE_MODEL_REGISTRY` | registry YAML 절대 경로 |
| `MEDIA_BRIDGE_ASSET_ROOT` | 전용 asset 디렉터리 절대 경로 |
| `MEDIA_BRIDGE_RECEIPT_SECRET` 또는 `_FILE` | 32바이트 이상 receipt Secret |
| `MEDIA_BRIDGE_OCR_ENDPOINT` | credential-free HTTPS OCR endpoint |
| `UPSTAGE_API_KEY` 또는 `_FILE` | 기본 Upstage OCR·Solar Secret |
| `MEDIA_BRIDGE_VISION_ENDPOINT` | credential-free HTTPS Vision endpoint |
| `MEDIA_BRIDGE_VISION_MODEL` | 변환용 Vision model exact ID |
| `MEDIA_BRIDGE_VISION_API_KEY` 또는 `_FILE` | Vision provider Secret |
| `MEDIA_BRIDGE_TENANT_ID` | stdio transport tenant |
| `MEDIA_BRIDGE_SERVICE_TOKEN` 또는 `_FILE` | HTTP bearer Secret |
| `MEDIA_BRIDGE_OMNIROUTE_BASE_URL` | optional OmniRoute `/v1/responses`; 설정 시 ingress 활성화 |
| `MEDIA_BRIDGE_OMNIROUTE_API_KEY` 또는 `_FILE` | OmniRoute Secret |

registry 형식은 `config/model_registry.example.yaml`을 복사한 뒤 실제 검증 정보와 만료 시각을
갱신합니다. model 이름 추측은 지원하지 않습니다.

## 실행 entrypoint

아래 명령은 개발용 실행 진입점입니다. 이번 작업에서는 서비스 등록이나 원격 배포를 수행하지
않았습니다.

```bash
.venv/bin/media-bridge-stdio
.venv/bin/media-bridge-http
```

HTTP는 기본적으로 `127.0.0.1:8000`에 바인딩합니다. `/mcp`, `/assets`, 활성화된
`/v1/responses` 모두 bearer 및 `X-Media-Bridge-Tenant`가 필요합니다. 운영 OAuth/mTLS,
reverse proxy, 방화벽은 별도 배포 계층의 책임입니다.

## 강제 router 사용

일반 Codex·후속·subagent 요청은 Media Bridge provider의 `/v1/responses`를 사용해야 합니다.
라이브러리 직접 통합은 `RouterAdapter.invoke()`를 사용합니다. Non-Vision 호출에 기존
multimodal 대화 전체를 넘기지 않습니다. 자세한 연결 경계는 `docs/router-integration.md`에
있습니다.

배포 승인 후 사용할 Codex custom provider의 reference 형태는 다음과 같습니다. 이 설정은
이번 작업에서 PCWSL에 적용하지 않았습니다.

```toml
[model_providers.media_bridge]
name = "Media Bridge"
base_url = "http://127.0.0.1:8000/v1"
env_key = "MEDIA_BRIDGE_SERVICE_TOKEN"
env_http_headers = { "X-Media-Bridge-Tenant" = "MEDIA_BRIDGE_TENANT_ID" }
wire_api = "responses"
```

OmniRoute 직접 inference endpoint가 caller에서 계속 접근 가능하면 ingress를 우회할 수 있습니다.
운영 연결에서는 network/router 계층에서 Media Bridge만 OmniRoute에 접근하도록 강제해야 합니다.

## 검증

```bash
.venv/bin/pytest -q
.venv/bin/pytest --cov=media_bridge --cov-branch --cov-report=term-missing -q
.venv/bin/ruff check .
.venv/bin/mypy media_bridge
```

실제 provider 자격증명을 사용하는 OCR·Vision·Solar 호출, PCWSL Codex→실제 OmniRoute E2E,
운영 배포는 자동 테스트 범위가 아닙니다. 상세 증거는 `docs/testing/media-bridge.tdd.md`를
확인합니다.

## 기존 Solar 코드

`solar_error_analyzer/`와 서버 상위 경로의 단일 파일은 기준선 보존용 legacy snapshot입니다.
새 Media Bridge runtime, MCP 도구, router는 해당 curl 기반 코드나 직접 키 인자 경로를
사용하지 않습니다. legacy snapshot은 새 패키지의 보안 경계나 운영 진입점으로 간주하지
않습니다.
