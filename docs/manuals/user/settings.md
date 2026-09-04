# Media Bridge 설정 화면

Media Bridge를 시작한 뒤 다음 명령으로 로컬 설정 화면을 엽니다.

```bash
mb gui
```

화면을 자동으로 열 수 없는 서버에서는 출력된 주소를 SSH port forwarding을 통해 사용자의
브라우저에서 엽니다. 설정 화면과 API는 `127.0.0.1`에만 바인딩됩니다.

## 코딩 에이전트

`코딩 에이전트`에서 Media Bridge를 호출할 client를 선택합니다.

- `OpenCodex`: 1차 지원 대상
- `Eoul Gateway`: Eoul Gateway를 통한 연결
- `OpenAI Responses 호환`: 다른 Responses 호환 코딩 에이전트

`연결 정보 확인`을 누르면 에이전트에 설정할 base URL과 `/v1/responses` 주소를 확인할 수
있습니다. 이 시험은 외부 Provider를 호출하지 않습니다.

## Non-Vision LLM

기본값은 Upstage Solar와 `solar-pro4`입니다. 다른 텍스트 전용 LLM은 `사용자 정의`를 선택하고
다음을 입력합니다.

- API 방식: OpenAI 호환 `Chat Completions` 또는 `Responses`
- Endpoint
- 모델 ID
- API Key
- 기존 환경변수를 대체 입력으로 사용할 경우 환경변수 이름

API Key는 일반 설정 파일에 저장되거나 화면에 다시 표시되지 않습니다. Windows에서는 현재
사용자 DPAPI로 보호하고, Linux headless 환경에서는 사용자만 읽을 수 있는 `0600` credential
파일에 일반 설정과 분리해 저장합니다. 환경변수 방식도 호환 목적으로 계속 사용할 수 있습니다.

`LLM 연결 시험`은 짧은 텍스트 요청을 실제 선택 Provider로 전송하므로 Provider 사용량이 발생할
수 있습니다. 성공하면 모델과 응답 텍스트를 표시하며 API Key 원문은 표시하지 않습니다.

## Vision / OCR 처리 엔진

1차 지원 엔진은 `Upstage Document Parse`입니다. Endpoint, API Key와 시험 이미지 또는 PDF를
선택하고 `OCR 연결 시험`을 누르면 실제 추출 텍스트가 화면에 표시됩니다.

일반 장면 이해용 Vision 모델은 Document Parse와 다른 기능입니다. 이 버전은 문서·스크린샷의
텍스트 추출을 우선 지원하며, 다른 Vision/OCR 제품은 `mediaProcessor` adapter로 추가합니다.

## 전체 흐름 시험

파일과 질문을 입력하고 `전체 파이프라인 시험`을 누르면 다음 순서가 실행됩니다.

1. 이미지 또는 PDF를 미디어 처리 엔진으로 전송합니다.
2. 추출된 텍스트를 확인합니다.
3. 원본 미디어를 제거합니다.
4. 질문과 추출 텍스트만 Non-Vision LLM으로 전송합니다.
5. 최종 답변과 `originalMediaForwarded: false`를 표시합니다.

미디어 처리에 실패하면 설정의 차단 정책에 따라 Non-Vision LLM은 호출하지 않습니다.

## 저장과 적용

`설정 저장`을 누르면 API Key와 일반 설정을 분리해 저장합니다. 포트가 같으면 Provider·모델·키
변경은 실행 중 runtime에 다시 로드됩니다. 포트를 변경하면 listener를 옮겨야 하므로 다음 명령으로
한 번 재시작합니다.

```bash
mb service restart
mb health --json
```

잘못된 URL, 지원하지 않는 프로토콜, 빈 모델, 범위를 벗어난 포트는 저장되지 않습니다.

기존 PostgreSQL·서명 snapshot·Control Plane 기반 `managed` 모드는 별도로 유지되며 npm
`personal` 설정 화면과 섞이지 않습니다.
