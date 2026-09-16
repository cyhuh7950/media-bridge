# 소비자 프로그램 연동 메뉴얼

상태: 2026-09-15 확인 기준

이 문서는 Media Bridge 소스를 변경하지 않고, ysna-server에 설치된 Media Bridge를 다른 프로그램에서 호출하기 위한 소비자 측 설정 절차를 설명합니다. 대상은 Daon2, Daon2-RAG, Eoul Agent, Eoul Gateway입니다.

## 설치 순서와 주소 결정

Media Bridge는 먼저 설치할 수 있지만 `npm install`만으로 네트워크 주소를 추측하거나 변경하지
않습니다. 설치 자동화는 Media Bridge 설치 후 실행 환경을 알고 있는 단계에서 `mb init`에 bind
주소를 전달하고, 이어서 Eoul Gateway가 같은 주소의 endpoint를 사용하도록 구성합니다.

시스템 전역 npm 경로에 쓸 권한이 없는 계정은 사용자 prefix와 PATH를 먼저 설정합니다.

```bash
npm config set prefix "$HOME/.local"
npm install -g @cyhuh/media-bridge
echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"
export PATH="$HOME/.local/bin:$PATH"
command -v mb
```

`command -v mb`가 경로를 출력한 뒤 아래 초기화를 실행합니다.

```bash
npm install -g @cyhuh/media-bridge
mb init --host <Media-Bridge를 열 주소> --port 8642
mb service install
mb service start
```

호스트에서 직접 실행되는 Gateway는 `127.0.0.1`을 사용합니다. Docker Gateway는 Media Bridge가
실제로 해당 Docker host gateway에서 수신하도록 설정된 경우에만 그 gateway 주소를 사용합니다.
주소를 정하지 않으면 Media Bridge 기본 bind는 `127.0.0.1`입니다. 따라서 Docker Gateway가
이미 설치된 Media Bridge에 연결할 때 endpoint만 임의로 `172.17.0.1`로 바꾸면 연결되지 않습니다.

## 1. 현재 서버 연결 정보

ysna-server에서 확인된 Media Bridge는 다음 주소에 바인딩되어 있습니다.

| 항목 | 값 |
| --- | --- |
| 주소 | `127.0.0.1:8642` |
| Responses endpoint | `http://127.0.0.1:8642/v1/responses` |
| API base URL | `http://127.0.0.1:8642/v1` |
| 상태 확인 | `mb status`, `mb health --json`, `mb ready` |
| 현재 설치 버전 | `@cyhuh/media-bridge@0.1.12` |

Media Bridge가 loopback(`127.0.0.1`)에만 열려 있으므로, 호출하는 프로그램이 ysna-server에서 실행될 때만 위 주소를 그대로 사용합니다. 노트북에서 연 SSH 터널(`ssh -L 18765:127.0.0.1:8642 ...`)은 노트북의 브라우저나 노트북에서 실행하는 시험 클라이언트용입니다. ysna-server에서 실행되는 Daon2나 Gateway의 설정값을 `18765`로 넣으면 안 됩니다.

### Docker 소비자를 같은 PC에서 호출하는 경우

Media Bridge는 npm 설치 시 기본적으로 `127.0.0.1`에만 bind됩니다. Docker 컨테이너에서 호출해야
하면 설치 프로그램에서 해당 PC의 Docker bridge gateway를 명시적으로 저장합니다.

```bash
docker network inspect bridge --format '{{range .IPAM.Config}}{{.Gateway}}{{end}}'
mb init --host 172.17.0.1 --port 8642
mb service restart
```

위 주소는 예시이며 모든 PC에 고정하지 않습니다. 첫 명령의 실제 결과를 `--host`에 넣어야 합니다.
비대화식 설치는 `MB_HOST=<사설-IPv4> MB_PORT=8642 mb init`을 사용합니다. loopback과 사설 IPv4만
허용하므로 공인 주소는 설정할 수 없습니다. `--host`를 생략하면 기본값 `127.0.0.1`을 유지하며,
다른 PC에 패키지를 다시 설치해도 그 PC의 설정이 자동으로 `172.17.0.1`로 바뀌지 않습니다.

### 다른 PC에서 지속적으로 사용하는 경우

SSH 터널은 임시 점검이나 단기 사용에는 적합하지만, 프로세스 종료·네트워크 단절·재부팅 때 다시 열어야 합니다. 여러 PC의 Daon2, Daon2-RAG, Eoul Gateway 또는 Eoul Agent가 지속적으로 사용해야 한다면 ysna-server에 HTTPS Reverse Proxy를 등록하는 운영 구성이 적합합니다.

```text
다른 PC의 소비자 프로그램
  -> HTTPS Reverse Proxy (허용된 DNS 이름과 TLS)
  -> ysna-server의 127.0.0.1:8642
  -> Media Bridge /v1/responses
```

Reverse Proxy를 사용할 때 소비자 프로그램의 API base URL은 `http://127.0.0.1:8642/v1`이 아니라 다음처럼 Proxy의 HTTPS 주소를 사용합니다.

```text
https://<Media-Bridge-허용-DNS>/v1
```

운영 등록 시 다음 조건을 지킵니다.

- TLS 인증서를 사용하고 HTTP 평문 외부 공개는 허용하지 않습니다.
- 방화벽은 승인된 소비자 PC 또는 사설망만 Proxy 포트에 접근하도록 제한합니다.
- Proxy는 내부 upstream을 `http://127.0.0.1:8642`로 고정하고 임의 upstream 전달을 허용하지 않습니다.
- 요청 본문, `Authorization` 헤더, tenant 헤더를 Proxy access log에 기록하지 않습니다.
- Media Bridge의 Bearer 토큰과 `X-Media-Bridge-Tenant` 헤더를 소비자에서 그대로 전달하되, 토큰을 URL query나 문서에 넣지 않습니다.
- Proxy 등록 후 각 소비자에서 `/v1/responses` 최소 text 요청과 실제 Provider readiness를 별도로 확인합니다.

Media Bridge의 HTTPS 경계와 예시 profile은 [`docs/install/https-reverse-proxy.md`](../../install/https-reverse-proxy.md)를 따릅니다. 이 구성은 Media Bridge 소스를 변경하는 작업이 아니라 ysna-server의 배포·네트워크 계층을 설정하는 작업입니다.

## 2. 공통 인증 설정

HTTP 호출에는 두 값이 필요합니다.

```text
Authorization: Bearer <Media Bridge service token>
X-Media-Bridge-Tenant: <tenant id>
```

서비스 토큰 원문은 ysna-server의 Media Bridge runtime secret 저장 위치에서 읽어야 합니다. 토큰을 소스, Git, DB의 일반 문자열, 화면 캡처, 문서에 넣지 않습니다. 소비자 프로그램은 각 제품이 지원하는 Secret file 또는 Secret Store 참조로 주입합니다.

최소 호출 형태는 다음과 같습니다.

```bash
curl -sS -X POST http://127.0.0.1:8642/v1/responses \
  -H "Authorization: Bearer ${MEDIA_BRIDGE_SERVICE_TOKEN}" \
  -H "X-Media-Bridge-Tenant: ${MEDIA_BRIDGE_TENANT_ID}" \
  -H 'Content-Type: application/json' \
  -d '{"model":"<실제 Media Bridge 모델 ID>","input":"연결 확인"}'
```

`<실제 Media Bridge 모델 ID>`는 설치된 runtime의 모델 원장과 외부 Provider 계약으로 확인한 값을 사용합니다. 모델명을 추측해 문서나 설정에 고정하지 않습니다.

## 3. Daon2 설정

### 현재 코드 기준의 제한

Daon2 Admin의 Model Registry Provider 등록 화면은 승인된 카탈로그만 선택하도록 되어 있습니다. 현재 카탈로그에는 `cerebras`, `groq`, `mistral`, `openrouter`, `upstage`, `gemini`, `claude`, `openai`, `ollama`가 있고 `media_bridge`는 없습니다. Provider 생성 API도 `provider_code`만 받고 서버의 승인된 baseline에서 `base_url`과 `secret_ref`를 채웁니다.

따라서 현재 화면에서 임의로 `media_bridge`를 입력하는 것만으로는 등록되지 않습니다. 이것은 Media Bridge의 문제나 서버 장애가 아니라 Daon2 소비자 측 Provider 카탈로그·baseline이 Media Bridge를 아직 정의하지 않은 상태라는 뜻입니다. Daon2 소스에 소비자용 Provider profile을 추가하는 작업이 필요한 경우, 별도 개발·검증 절차로 처리해야 합니다.

### 소비자 측에 추가해야 할 Provider 계약

Daon2의 Provider profile에 다음 의미를 등록합니다.

| 필드 | Media Bridge용 값 |
| --- | --- |
| provider code | `media_bridge` (소비자 측에서 승인할 내부 식별자) |
| provider type | `external_api` |
| base URL | `http://127.0.0.1:8642/v1` (Daon2가 ysna-server에서 실행될 때) |
| Responses 경로 | `/responses` (`POST /v1/responses`) |
| 인증 | Bearer service token + `X-Media-Bridge-Tenant` 헤더 |
| 후보 역할 | 우선 `text`; Media 입력 계약을 검증한 뒤 필요한 역할만 추가 |
| execution policy | `external_provider` |
| contract version | Daon2가 요구하는 `v1` |
| secret reference | 토큰 원문이 아닌 Daon2가 읽을 수 있는 Secret 참조 |

Daon2의 기존 OpenAI baseline을 Media Bridge 주소로 바꾸어 우회하는 방식은 권장하지 않습니다. OpenAI baseline은 공식 OpenAI 주소와 Chat Completions 경로를 전제로 하므로 Responses endpoint와 헤더 계약을 정확히 표현하지 못할 수 있습니다.

### Provider·Model·역할 매핑 순서

Media Bridge용 Provider profile이 소비자 코드에 반영된 뒤 Admin 화면에서 다음 순서로 처리합니다.

1. **Provider 등록**: Provider 등록에서 `media_bridge`를 선택합니다.
2. **연결 검증**: Provider connection test 또는 activation readiness 재검증을 실행합니다. `127.0.0.1:8642` 연결, Bearer 인증, tenant 헤더가 모두 성공해야 합니다.
3. **Provider 활성화**: 현재 상태가 `inactive`인지 확인한 뒤 `active`로 변경합니다.
4. **Model 등록**: Media Bridge가 실제로 제공하는 모델 ID를 `model_code`와 `model_name`으로 등록하고 `task_role=text`, `execution_policy=external_provider`, `contract_version=v1`를 사용합니다.
5. **Model 활성화**: 연결 검증이 성공한 뒤 모델을 `active`로 변경합니다.
6. **역할 매핑 활성화**: `text` 역할의 active mapping 대상으로 해당 모델을 선택하고 우선순위를 지정합니다.
7. **실제 Daon2 요청**: Daon2가 직접 Provider API를 호출하는지, 또는 내부 adapter를 거치는지 확인한 뒤 최소 text 요청 1건을 실행합니다.

역할 매핑은 모델 활성화보다 먼저 할 수 없습니다. Provider·Model이 모두 active가 아니거나 readiness evidence가 없으면 매핑을 활성화하지 않습니다.

## 4. Daon2-RAG 설정

Daon2-RAG도 같은 Provider→Model→역할 매핑 원칙을 사용하지만, 역할별로 Media Bridge를 구분해야 합니다.

- `text`: Media Bridge Responses 계약으로 연결할 수 있는 후보입니다.
- `embedding`: Media Bridge의 `/v1/responses`는 embedding endpoint가 아니므로 매핑하지 않습니다. 기존 embedding Provider와 `/embeddings` 계약을 유지합니다.
- `reranker`: Media Bridge Responses만으로 대체할 수 있다고 확인되지 않았으므로 기존 reranker 계약을 유지합니다.
- `vision`: 이미지 입력을 실제로 Media Bridge가 처리하는 소비자 경로와 모델 capability를 별도 검증한 뒤에만 사용합니다.

따라서 RAG 전체를 Media Bridge 하나로 바꾸는 설정은 현재 계약으로 확인되지 않았습니다. 우선 `text` 역할만 연결하고, 검색용 embedding·reranker는 기존 Provider를 유지하는 구성이 안전한 기본값입니다.

## 5. Eoul Gateway 설정

Eoul Gateway는 Provider·Model·Route·Policy를 순서대로 구성합니다. Media Bridge는 Gateway가 호출하는 내부 Provider endpoint로 등록합니다.

### Provider

Gateway Console의 Provider 등록에서 다음 개념을 사용합니다.

| 필드 | 값 또는 규칙 |
| --- | --- |
| adapterId | `openai-compatible` 또는 Responses를 지원하는 Gateway adapter의 실제 ID |
| endpoint/base URL | `http://127.0.0.1:8642/v1` (Gateway가 ysna-server에서 실행될 때) |
| protocol | Media Bridge의 Responses 계약과 일치하는 값 |
| secretRef | Media Bridge service token을 가리키는 Secret reference |
| local network | loopback `127.0.0.1`, TCP port `8642`, `http`를 명시적으로 허용 |
| status | 연결 시험 성공 후 `ACTIVE` |

Gateway의 현재 사용자 메뉴얼은 Provider에 API key 원문을 저장하지 않고 Secret reference를 사용하도록 규정합니다. Media Bridge 토큰도 같은 방식으로 등록합니다.

### Model·Route·Policy

1. Provider에 속한 실제 Media Bridge 모델 ID로 Model draft를 만듭니다.
2. Provider ID와 Model ID를 참조하는 Route를 만듭니다.
3. Route의 text/Responses 연결 시험을 실행해 `VERIFIED` 상태를 확인합니다.
4. 해당 Route를 포함하는 Policy를 만들고 발행합니다.
5. 발행된 logical model ID를 사용하는 Gateway `/v1/responses` 요청으로 최소 text 요청을 실행합니다.

Gateway의 외부 공개 API와 Media Bridge의 내부 API는 별개입니다. 애플리케이션은 Gateway URL을 호출하고, Gateway만 Media Bridge loopback 주소를 호출하도록 구성합니다.

## 6. Eoul Agent 설정

현재 Eoul Agent의 설정 예시에는 Media Bridge 전용 환경변수나 OpenAI Responses Provider 항목이 확인되지 않았고, 기본 Connector 모드는 `recorded`입니다. 따라서 `.env.example`에 주소만 추가한다고 Eoul Agent가 Media Bridge를 사용하게 되지는 않습니다.

권장 소비자 경로는 다음과 같습니다.

```text
Eoul Agent → Eoul Gateway의 발행된 logical model → Gateway의 Media Bridge Route → Media Bridge /v1/responses
```

Eoul Agent를 직접 Media Bridge에 연결하려면 Eoul Agent에 Responses client/connector와 다음 계약을 구현해야 합니다.

- base URL과 `/v1/responses` 경로
- Bearer service token Secret file 주입
- `X-Media-Bridge-Tenant` 헤더
- Responses 요청·streaming 응답 처리
- tool·follow-up 상태의 보존과 미지원 기능의 명시적 오류 처리

이 구현이 없으면 Agent의 `EOUL_*` 포트 설정이나 recorded Connector 설정만 바꾸어도 Media Bridge 호출이 발생하지 않습니다. 직접 연결을 선택할 경우에는 Eoul Agent의 계획 승인, 구현, 실제 ysna-server E2E 검증이 별도 작업입니다.

## 7. 연결 확인 순서

각 소비자에서 다음 순서로 확인합니다.

1. ysna-server에서 `mb status`, `mb health --json`, `mb ready`가 성공하는지 확인합니다.
2. 호출 프로세스가 ysna-server에서 실행되는지 확인합니다. 다른 호스트이면 `127.0.0.1`을 사용하지 않습니다.
3. Secret file이 존재하고 호출 프로세스가 읽을 수 있는지만 확인합니다. 원문은 출력하지 않습니다.
4. 최소 text Responses 요청을 1회 실행합니다.
5. 소비자 쪽 Provider connection test/readiness가 성공하는지 확인합니다.
6. Provider active → Model active → 역할 mapping active 순서를 확인합니다.
7. 실제 애플리케이션 요청에서 사용한 Provider, Model, Route/logical model ID를 기록합니다.

### 오류별 판별

| 증상 | 우선 확인할 것 |
| --- | --- |
| 연결 거부 | 호출 프로세스 위치, `127.0.0.1:8642`, Media Bridge runtime 상태 |
| 401/403 | Bearer 토큰 주입, tenant 헤더, Secret reference |
| Provider 등록 거부 | 소비자 Provider catalog/baseline에 `media_bridge`가 정의되었는지 |
| Model 활성화 거부 | Provider active 여부, 실제 모델 ID, readiness evidence |
| RAG embedding 실패 | embedding 역할을 Media Bridge에 잘못 매핑했는지 |
| 요청은 성공하지만 Media Bridge 로그가 없음 | 애플리케이션이 Gateway 또는 다른 Provider를 호출하는지 |
| 노트북에서만 접속 실패 | SSH 터널 사용 여부와 포트 `18765`를 시험 클라이언트에만 사용했는지 |

## 8. 현재 판정

- ysna-server의 Media Bridge runtime은 실행 중이며 health는 200입니다.
- Daon2/Daon2-RAG의 현재 Provider 카탈로그에는 Media Bridge가 없어 UI만으로 등록할 수 없습니다.
- Daon2-RAG의 embedding·reranker 역할은 Media Bridge Responses endpoint로 대체된다고 확인되지 않았습니다.
- Eoul Gateway는 Provider/Route 계층에서 Media Bridge를 소비하도록 구성하는 경로가 정합적입니다.
- Eoul Agent는 현재 설정 파일만으로 직접 연결된다는 근거가 없으며, Gateway 경유 또는 별도 Responses connector 구현이 필요합니다.

이 문서는 소비자 측 설정 절차를 기록한 것이며 Media Bridge 소스·배포·런타임 설정을 변경하지 않습니다.
