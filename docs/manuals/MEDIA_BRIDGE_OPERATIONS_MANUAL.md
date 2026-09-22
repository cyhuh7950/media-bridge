# Media Bridge 운영 관리 매뉴얼

## 문서 목적

이 매뉴얼은 배포형 Media Bridge의 관리 콘솔에서 Provider, 라우팅, 모델, 정책, 접근 키와 Snapshot을 등록하고 운영하는 방법을 설명합니다. Provider와 credential은 DB 설정을 정본으로 사용합니다. Media Bridge는 미디어 입력을 검사·분석한 뒤 허용된 요청을 Non‑Vision LLM Provider로 전달합니다.

## 설정 순서

권장 순서는 다음과 같습니다.

```text
Provider 등록
→ 필요할 때 모델 override 등록
→ 라우팅 프로필에서 분석 Provider와 LLM Provider 연결
→ 정책 등록
→ 외부 호출용 접근 키 발급
→ 현재 설정 검증 및 Snapshot 발행
→ 외부 연결 시험
```

Provider와 라우팅이 없으면 분석 결과를 전달할 대상이 없고, Snapshot을 발행하지 않으면 Gateway가 변경된 설정을 운영 설정으로 사용하지 않습니다.

## Provider

Provider는 Media Bridge가 호출할 외부 분석 서비스와 LLM 서비스를 등록하는 메뉴입니다.

### 등록 대상

| 유형 | 역할 | 예시 |
| --- | --- | --- |
| 분석 Provider | 이미지·PDF·문서에서 내용을 추출하거나 분석 | `upstage-document-parse`, `openai-vision` |
| Non‑Vision LLM Provider | 분석 결과를 텍스트 모델로 처리 | `upstage-solar`, `omni-route` |

### 등록 방법

1. **Provider 등록**을 선택합니다.
2. Provider 유형을 선택합니다.
3. 카탈로그에서 Provider를 선택합니다. 선택하면 이름과 endpoint가 자동으로 채워집니다.
4. 필요하면 **기준 모델**을 입력합니다. 추론 등급을 지원하는 Non‑Vision LLM이면 Provider 기본값 또는 지원 등급도 선택합니다.
5. Provider API 키를 기존 DB credential 관리 경로로 저장하거나 이미 등록된 DB credential을 선택합니다. 새 Secret 파일은 요구하지 않습니다.
6. 등록합니다.

기준 모델은 선택 사항입니다.

- 기준 모델을 입력하면 해당 Provider 호출에 그 모델을 사용합니다.
- 비워두면 카탈로그에 정의된 Provider 기준 모델을 자동으로 사용합니다.

Provider API 키는 DB에서 암호화해 보관하며, 관리 화면은 원문을 다시 표시하지 않습니다. Gateway는 Provider ID를 기준으로 DB credential을 조회하므로 별도의 Gateway Secret 파일을 추가할 필요가 없습니다.

### Non‑Vision LLM 추론 등급

추론 등급은 Provider 유형이 **Non‑Vision LLM**일 때만 설정합니다. 선택한 카탈로그 Provider, API 프로토콜, 모델 조합이 지원하는 경우에만 선택지가 표시됩니다. 현재 Upstage Solar의 `solar-pro3` 및 `solar-pro4` Chat Completions 조합은 `low`, `medium`, `high`를 지원합니다.

- **Provider 기본값**은 추론 파라미터를 요청에 넣지 않아 Provider 기본 동작을 사용합니다. 새 Provider와 기존 설정 모두 이 값을 기본으로 유지합니다.
- 지원 등급을 선택하면 저장 후 Snapshot을 발행해야 실제 Gateway 요청에 반영됩니다. 설치형에서는 설정을 저장하면 LLM 연결 시험과 전체 흐름 시험 모두 같은 선택값을 사용합니다.
- 모델이나 프로토콜을 지원하지 않는 조합으로 바꾸면 기존 등급을 자동 적용하지 않습니다. 지원되는 등급 또는 Provider 기본값을 명시적으로 선택해야 저장할 수 있습니다.
- 분석 Provider, 이미지 변환 단계 및 분석 Provider와 Non‑Vision LLM 사이의 N:N 라우팅 설정은 추론 등급과 별개이며 변경되지 않습니다.

## 라우팅

라우팅 프로필은 분석 Provider와 Non‑Vision LLM Provider를 연결하는 메뉴입니다. 한 개만 연결하는 1:1 구성도 가능하고, 여러 분석 Provider와 여러 LLM Provider를 선택하는 N:N 구성도 가능합니다.

### 등록 항목

- **이름**: 프로필을 구분할 이름. 예: `기본 문서 분석`
- **분석 Provider**: 하나 이상 선택
- **Non‑Vision LLM Provider**: 하나 이상 선택
- **선택 전략**:
  - **우선순위**: 설정된 우선순위 순서로 선택
  - **대체 경로**: 앞선 Provider 실패 시 다음 Provider 사용
  - **상태 우선**: 정상 상태 Provider를 우선 선택
  - **비용 우선**: 비용 기준으로 선택

예를 들어 분석 Provider로 `upstage-document-parse`, `openai-vision`을 선택하고 Non‑Vision LLM Provider로 `upstage-solar`, `omni-route`를 선택하면 시스템이 분석 성공 여부와 선택 전략에 따라 전달 대상을 자동으로 결정합니다.

## 모델

모델 메뉴는 Provider의 기준 모델을 대체하거나, 사용할 모델의 capability 근거를 별도로 관리할 때 사용합니다.

### 등록 항목

- **모델 ID**: Provider가 실제로 받는 정확한 모델 식별자. 예: `solar-pro2`
- **Capability 근거**: 해당 모델이 텍스트 전용 Non‑Vision 모델임을 확인할 수 있는 문서, Provider 모델 목록, 또는 연결 시험 근거

모델 등록은 선택 사항입니다. 모델을 등록하지 않으면 Provider 등록에 지정한 기준 모델을 사용하고, Provider 기준 모델도 비어 있으면 카탈로그의 기본 모델을 사용합니다.

## 정책

정책은 미디어 입력 경계와 차단 방식을 정의합니다. 현재 화면에서 정책 이름을 등록하면 기본 안전 정책이 적용됩니다.

기본 정책은 다음과 같습니다.

| 항목 | 기본값 |
| --- | --- |
| 최대 파일 수 | 4개 |
| 최대 미디어 크기 | 2MiB |
| 최대 PDF 페이지 | 20페이지 |
| URL 입력 | 차단 |
| Base64 입력 | 허용 |
| Asset 입력 | 허용 |
| 로컬 경로 입력 | 차단 |
| Fail‑closed | 활성 |

Fail‑closed가 활성화되면 분석 Provider가 없거나 모델 capability를 확인할 수 없는 요청을 허용하지 않습니다. 정책을 등록하거나 수정한 뒤에는 Snapshot 발행을 해야 Gateway에 반영됩니다.

## 접근 키

접근 키는 외부 사용자, Agent, 애플리케이션이 Media Bridge Endpoint를 호출할 때 사용하는 키입니다. 관리자만 발급·폐기할 수 있습니다.

### 발급 항목

- **접근 키 이름**: 사용 목적이나 호출 주체. 예: `OmniRoute 배포형`
- **권한**:
  - `assets:write`: 이미지·PDF 업로드
  - `mcp:invoke`: MCP 호출
  - `responses:invoke`: Responses API 호출

발급 직후 원문 키가 한 번만 표시됩니다. 즉시 호출 주체의 Secret 관리 시스템에 저장해야 하며, 잃어버린 경우 기존 키를 복구하지 말고 새 키를 발급합니다. 사용 중지할 키는 선택 후 **선택 폐기**로 폐기합니다.

## Snapshot

Snapshot은 현재 DB 설정을 검증하고 운영용 서명 설정으로 발행하는 기능입니다. Provider, 모델, 라우팅, 정책을 변경한 뒤 다음 작업을 수행합니다.

1. **현재 설정 검증 및 발행**을 선택합니다.
2. 시스템이 draft 설정을 검증합니다.
3. 검증이 성공하면 서명 Snapshot이 발행됩니다.
4. Gateway가 새 Snapshot을 사용합니다.

잘못된 설정을 발행한 경우 Snapshot 목록에서 원하는 버전의 **이 버전으로 rollback**을 선택합니다. Snapshot 발행과 rollback은 관리자만 수행할 수 있습니다.

## 운영 시 확인 사항

- Provider를 등록했지만 라우팅 프로필에서 선택하지 않으면 요청 전달 대상이 되지 않습니다.
- 모델은 선택 사항이며, 미등록 시 Provider 기준 모델이 자동 사용됩니다.
- 설정을 바꾼 뒤 Snapshot을 발행하지 않으면 Gateway에 변경 사항이 반영되지 않습니다.
- 접근 키 원문은 발급 순간에만 표시됩니다.
- Provider API 키와 외부 호출용 접근 키는 서로 다른 키입니다.
- Provider API 키는 downstream Provider 호출용이고, 접근 키는 Media Bridge Endpoint 호출용입니다.
- 정책 화면은 현재 정책 이름과 기본 안전값을 관리합니다. 특정 라우팅 프로필에 정책을 직접 연결하는 별도 편집 항목은 현재 콘솔에 노출되어 있지 않습니다.
