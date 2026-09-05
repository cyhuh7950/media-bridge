# Media Bridge 연결과 시험

## 시작 확인

```bash
mb start
mb ready --wait --timeout 60
mb health --json
mb gui
```

`ready`와 `health`는 Media Bridge runtime 자체 상태입니다. Provider 연결 성공을 의미하지는
않으므로 설정 화면에서 다음 시험을 순서대로 실행합니다.

1. `연결 정보 확인`: 코딩 에이전트에 입력할 Responses 주소를 확인합니다.
2. `LLM 연결 시험`: 선택한 Non-Vision LLM에 실제 텍스트를 보냅니다.
3. `OCR 연결 시험`: 시험 이미지/PDF에서 실제 텍스트를 추출합니다.
4. `전체 흐름 시험` 영역의 `질문에 첨부할 이미지/PDF`에서 파일을 선택하고 질문을 입력한 뒤
   `전체 파이프라인 시험`을 누릅니다. OCR 결과만 LLM에 보내고 최종 응답을 확인합니다.
   이 첨부 파일은 위쪽 OCR 연결 시험에 사용한 파일과 독립적입니다.

실제 Provider 시험은 외부 API 호출이므로 사용량이 발생할 수 있습니다. Media Bridge는 API Key
원문과 업로드 파일을 browser storage에 저장하지 않으며, 응답 화면에도 API Key를 반환하지
않습니다.

## 코딩 에이전트 연결

Codex CLI 직접 연결은 [별도 연결·해제 안내](connect-codex-cli.md)를 따릅니다.
직접 연결 기능의 개발 후보 검증과 공개 npm 배포 여부를 구분합니다.
OpenCodex와 Eoul Gateway는 코딩 에이전트가 아니라 연결·라우팅 gateway입니다.

코딩 에이전트의 OpenAI Responses provider base URL을 설정 화면의 `baseUrl`로 맞춥니다. 기본값은
다음과 같습니다.

```text
http://127.0.0.1:8642/v1
```

실제 요청 URL은 다음과 같습니다.

```text
http://127.0.0.1:8642/v1/responses
```

OpenCodex, Eoul Gateway 또는 다른 Responses 호환 client가 이 주소로 요청하면 Media Bridge가
미디어를 처리하고 선택한 Non-Vision LLM의 답변을 Responses 형식으로 반환합니다.

## 판정 구분

- `health PASS`: Media Bridge process와 HTTP listener 정상
- `LLM 시험 PASS`: 선택 LLM endpoint·모델·credential 정상
- `OCR 시험 PASS`: 선택 미디어 처리 endpoint·credential·파일 처리 정상
- `전체 흐름 PASS`: OCR → 원본 제거 → 텍스트 LLM → 최종 응답 정상
- `코딩 에이전트 PASS`: 실제 코딩 에이전트에서 같은 요청과 응답을 확인

앞 단계만 통과하고 뒤 단계가 실행되지 않았다면 제품 전체 PASS로 기록하지 않습니다.
