# LLM 추론 등급 설정 설계

상태: 설계 초안 — 신산님이 지원하는 Non‑Vision LLM의 모델/API별 추론 등급 설정과 실제 요청 반영 방향을 확인했다. 분석 Provider 및 N:N 연결은 보존한다. 이 수정본의 검토와 구현 계획 승인은 남아 있다.

## 1. 목적과 완료 기준

배포형과 설치형 Media Bridge에서 추론 등급을 지원하는 Non‑Vision LLM Provider/모델의 추론 등급을 설정하고, 실제 Provider API 요청에 반영한다. Upstage Solar는 대표 예시이지 배포형 지원 대상을 Solar 하나로 제한하지 않는다. 설정은 DB 또는 설치형 정본 설정에서 저장·재시작 후 복구되며, 실행 경로는 선택된 Provider/API/모델에 맞는 필드로 변환해야 한다.

완료 시 다음을 만족한다.

- 배포형 관리 화면에서는 실제 실행 가능하며 지원 계약이 검증된 Non‑Vision LLM Provider/모델의 추론 설정을 조회·수정할 수 있다. 미지원 모델/API와 사용자 정의 Provider에는 설정 항목을 제공하지 않는다.
- 설치형 설정 화면에서는 현재 제품 선택지에 따라 Upstage Solar만 대상으로 한다. 설치형 사용자 정의 Provider는 이번 범위에서 제외한다.
- 분석 Provider 유형과 분석 Provider → Non‑Vision LLM 연결 동작·cardinality는 유지한다. 이 기능은 Vision/OCR 분석 단계나 그 연결을 바꾸지 않는다.
- 기본 선택은 `Provider 기본값`이며, 이때 추론 관련 필드를 downstream 요청에 추가하지 않는다.
- 명시적으로 등급을 선택하면 모델/API 계약에 맞는 필드와 값만 전송한다. 지원하지 않는 조합은 숨기거나 명확하게 거부하며 조용히 다른 등급으로 대체하지 않는다.
- 종전 Provider 설정과 설치형 설정 파일, 기존 서명 snapshot은 추론 설정이 없는 상태로 계속 유효하고 기존 요청 payload는 달라지지 않는다.
- 내부 reasoning trace는 일반 응답, UI, 로그, 감사 이벤트에 노출하지 않는다. 이 기능은 추론량 설정만 제어한다.

## 2. 현재 구조와 결손

- 배포형 `Provider` DB 모델은 `kind`, `model_id`, `protocol`, endpoint, credential 참조를 갖지만 추론 등급을 저장하는 필드가 없다. API의 `ProviderCreate`/`ProviderUpdate`에도 해당 항목이 없다.
- 배포형 Provider 카탈로그에는 여러 Non‑Vision LLM이 정의되어 있으나, 카탈로그에 있다는 사실만으로 Gateway 실행이 지원된다고 간주할 수 없다. 추론 설정은 실제 실행 가능한 Provider/API adapter와 검증된 모델 capability가 모두 있는 조합에만 제공한다.
- 설치형 npm 설정 화면은 `textLlm` Provider·protocol·endpoint·model을 편집하고 `config.json`을 정본으로 사용하지만, 폼 payload와 저장 검증에 reasoning 항목이 없다.
- 설치형 `SolarResponsesDownstream`은 Chat Completions 요청에 모델·메시지·도구를, Responses 요청에 모델·입력·도구를 구성한다. 설정된 추론 등급을 받을 인자나 API 필드가 없다.
- 현재 배포 Gateway entrypoint는 DB의 `upstage-solar` Provider를 찾아 고정 Solar downstream을 구성한다. Snapshot의 Provider 목록만으로 다른 Provider가 실행 가능하다고 보지 않는다. 다른 Non‑Vision LLM의 추론 설정을 제공하려면 DB Provider 선택부터 downstream 생성·호출까지 실제 실행 경로가 이어져야 한다.
- Data Plane은 서명 snapshot 기반으로 동작하므로 배포형 설정은 DB 저장만으로 실행에 반영되지 않는다. snapshot 발행·검증 및 런타임 Provider 선택·adapter까지 동일 계약을 유지해야 한다.

주요 코드 근거: `media_bridge_control/models.py`, `media_bridge_control/schemas.py`, `media_bridge_control/provider_catalog.py`, `media_bridge_control/snapshots.py`, `media_bridge_personal/npm_runtime.py`, `media_bridge_personal/solar_responses.py`, `media_bridge_local/core/config_snapshot.py`.

## 3. 승인된 방향

### 설정 단위와 정본

- 전역 단일 값이 아니라 **Provider와 모델 조합별** 설정으로 한다. 현재 데이터 모델에서 Provider가 모델 ID 하나를 보유하므로 Provider 설정에 귀속시키고, 모델 ID가 바뀌면 지원 선택지도 다시 검증한다.
- 배포형 정본은 기존 DB Provider 설정이다. 선택값은 해당 Non‑Vision LLM Provider/모델 설정에 저장되고, snapshot을 통해 실행 가능한 Data Plane downstream까지 전달된다. Secret 원문은 기존 DB credential 경로만 사용하며 snapshot에 넣지 않는다.
- 설치형 정본은 기존 `~/.media-bridge/config.json`의 `textLlm` 설정이다. 개인용 credential 저장 위치와 기존 설정 파일 포맷을 유지한다.
- 설치형 및 배포형의 설정명은 `reasoningEffort`(JSON API wire name `reasoning_effort`)로 통일한다. 값이 없거나 `provider_default`이면 제공사 기본 동작을 보존한다.

### UI 동작

- 배포형의 Non‑Vision LLM Provider/모델 설정과 설치형 Solar 설정에 `추론 등급` selector를 제공한다. 분석 Provider 설정에는 표시하지 않는다.
- 지원 선택은 `Provider 기본값`과 현재 Provider/API/모델에서 검증된 등급의 교집합으로 제한한다. `없음/최소/낮음/보통/높음/최대`처럼 보편 enum을 모든 Provider에 강제로 보여주지 않는다.
- 기존 설정을 불러올 때 필드가 없으면 `Provider 기본값`으로 표시한다. 저장 시에도 선택값을 명시적으로 유지한다.
- 설정 저장은 기존 인증·권한·CSRF 경계와 local-origin 경계를 그대로 따른다. credential 원문을 새로 요구하거나 노출하지 않는다.

## 4. Provider 요청 변환

공통 설정값은 정규화된 의미 등급이며, 실제 요청 직전에 protocol adapter가 Provider API 필드로 변환한다. 일반 텍스트 요청과 전체 파이프라인 테스트는 같은 설정값을 사용한다. OCR·이미지 분석 Provider 설정은 이번 범위에 넣지 않는다.

| Provider/API 계약 | 요청 변환 원칙 | 모델별 제약 |
| --- | --- | --- |
| OpenAI Responses | `reasoning.effort` 사용 | 실제 실행되는 Provider 및 model ID의 지원 조합과 등급만 노출 |
| OpenAI-compatible Chat Completions / Upstage Solar | Provider가 명시적으로 지원하는 `reasoning_effort` 계약 사용 | OpenAI 호환이라는 이유만으로 지원을 추정하지 않는다. Solar는 대표 예시이며 배포형을 Solar로 한정하지 않는다. |
| Gemini native GenerateContent | 검증된 모델 계약에 맞는 `thinkingConfig` 필드 사용 | 모델별 지원 등급·budget을 검증하고 미지원 선택지를 숨긴다. |
| Anthropic Messages | 검증된 모델/API 계약에 맞는 thinking 설정 사용 | API 및 모델 버전별 필드·등급을 구분하고 미지원 전환을 추정하지 않는다. |
| Ollama 또는 기타 Provider | 명시적으로 등록·검증된 model/API adapter만 지원 | 카탈로그 등록이나 유사한 필드명만으로 지원을 가정하지 않는다. |

Provider 기본값은 어떤 provider-specific parameter도 보태지 않는다. API가 선택 등급을 거부하면 오류를 안전한 오류 코드로 전달하고, 자동으로 `medium` 등 다른 값으로 retry하지 않는다. 사용자 요청에 포함된 임의 reasoning 필드는 관리자 설정을 우회하지 못한다.

등급 표기와 provider mapping은 모델/API 버전에 따라 달라질 수 있으므로, 구현은 이름 유사성만으로 지원 여부를 추정하지 않는다. Provider catalog/프로토콜 adapter가 명시한 model family 지원 정보와 만료일이 있는 검증 근거를 사용한다. 지원 정보가 없는 custom provider는 기본값만 제공한다.

## 5. 호환성·보안·오류 처리

- DB migration은 nullable 또는 기존 데이터의 기본값 해석을 통해 구 Provider row를 보존한다. 필드가 없는 레코드는 `provider_default`로 해석한다.
- snapshot body에 비밀정보를 추가하지 않는다. 새로운 설정은 기존 digest/signature 대상에 포함된다. 이전 snapshot은 필드 부재만으로 거부되지 않아야 한다.
- 설치형 설정 validator는 필드 부재를 허용하고, 알 수 없는 값·잘못된 형식은 저장 단계에서 거부한다.
- LLM 호출 외부에서 선택 등급을 덮어쓰지 않는다. logs, event details, usage records에는 선택 등급 외에 프롬프트·reasoning trace·credential을 추가하지 않는다.
- 선택 등급을 모델이 실제로 적용했는지는 API 응답이 보장하지 않을 수 있다. 계약 fixture는 전송 payload를 검증하고, 실제 제공사 적용은 별도 sandbox/E2E 증거로 구분한다.

## 6. 검증 기준

1. API/DB: Provider create/read/update 및 migration round-trip에서 선택 등급이 보존되고, 구 Provider는 `provider_default`로 동작한다.
2. Control UI: 생성·편집·재조회 시 선택값이 일치하고, analysis Provider 화면에는 LLM 전용 설정이 나타나지 않는다.
3. Local UI/config: 폼 조회·저장·재시작 이후 값이 보존된다. 기존 config 파일은 변경 없이 정상 로드된다.
4. Adapter contract: OpenAI Responses, OpenAI Chat/Upstage, Gemini 2.5·3, Anthropic adaptive/지원 legacy, Ollama 및 기본값 각각에 대해 예상 JSON과 미지원 값 거부를 검증한다.
5. Snapshot/runtime: DB 값→snapshot 서명→Data Plane 검증→downstream payload까지 값이 유지되고, 기존 snapshot도 로드된다.
6. 보안/회귀: API/로그/snapshot에 credential 및 reasoning trace가 없고, Provider 기본값에서는 이전 downstream payload와 동일하다.
7. 운영 Provider 호출은 사용자 승인된 sandbox/배포 범위에서만 수행한다. 단위·fixture 테스트만으로 외부 모델이 해당 등급을 적용했다고 판정하지 않는다.

## 7. 제외 범위와 다음 승인 단계

- 모델 자동 discovery, 비용·latency 정책 자동 조정, 임의 custom JSON 요청 파라미터 편집은 제외한다.
- OCR/Vision 분석 Provider의 추론 설정과 외부 client별 요청 옵션은 제외한다. 분석 Provider 등록과 Non‑Vision LLM에 대한 연결 동작은 보존한다.
- 이 문서는 구현 명세 검토용이다. 사용자 검토·승인 후 별도 구현 계획을 작성한다. DB schema migration이 필요하면 계획에서 기존 row 호환성과 적용 경계를 분명히 하고 별도 승인받는다. 실제 Provider 실행 범위는 테스트 근거로 특정한다.

## 8. 근거 문서

- OpenAI API reference: https://platform.openai.com/docs/api-reference/responses
- Google Gemini thinking: https://ai.google.dev/gemini-api/docs/thinking
- Upstage Solar Pro 4: https://www.upstage.ai/blog/ko/solar-pro-4
- Upstage Console API example: https://console.upstage.ai/api-keys?api=chat-reasoning
- Anthropic thinking guidance: https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/prompt-templates-and-variables
- Ollama thinking: https://docs.ollama.com/capabilities/thinking
- Ollama chat API: https://docs.ollama.com/api/chat
