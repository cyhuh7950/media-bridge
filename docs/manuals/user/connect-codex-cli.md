# Codex CLI 직접 연결

## 적용 상태

이 문서는 `codex/codex-direct` 개발 후보의 연결 방법입니다. 아직 공개 npm 버전에
이 기능이 배포되었다는 뜻은 아닙니다. 해당 기능을 포함한 runtime의 공개·검증 안내 후 사용합니다.
검증한 client는 WSL의 Codex CLI 0.153.4입니다. 데스크톱 앱·Claude Code 호환을 의미하지 않습니다.

연결은 `Codex CLI → Media Bridge → 설정한 텍스트 LLM`입니다.
이미지는 OCR로 텍스트화하며 원본 이미지를 Non-Vision LLM으로 보내지 않습니다.
OpenCodex/Eoul Gateway는 이 직접 연결에 필수 구성요소가 아닙니다.
파일 읽기·수정·명령 실행과 승인은 Codex가 담당합니다. Media Bridge는 도구를 실행하지 않습니다.

## 기존 Codex 설정을 보존하는 연결

Media Bridge와 Codex CLI를 같은 환경에서 실행합니다. `127.0.0.1`은 명령을 실행하는 환경
자체입니다. Windows의 localhost와 원격 서버의 localhost를 혼동하지 않습니다.

Media Bridge 설정 화면에서 텍스트 LLM과 OCR의 주소·모델·키를 설정하고 각각 연결 시험을 합니다.
화면의 전체 흐름 시험 성공은 코딩 도구 왕복 성공과 별개입니다.

전용 작업 폴더에서 별도 Codex 설정 디렉터리를 선택하고 다음과 같이 실행합니다.
`solar-pro4`와 포트는 Media Bridge에 설정한 값과 같아야 합니다.

```bash
mkdir -p .media-bridge-codex
CODEX_HOME="$PWD/.media-bridge-codex" codex exec \
  --ignore-user-config --skip-git-repo-check --sandbox read-only \
  -c 'model_provider="media_bridge"' \
  -c 'model="solar-pro4"' \
  -c 'model_providers.media_bridge.name="Media Bridge"' \
  -c 'model_providers.media_bridge.base_url="http://127.0.0.1:8642/v1"' \
  -c 'model_providers.media_bridge.wire_api="responses"' \
  -c 'model_providers.media_bridge.requires_openai_auth=false' \
  -c 'web_search="disabled"' \
  '현재 작업 폴더의 파일 목록을 읽고 설명해 주세요. 수정하지 마세요.'
```

이 명령은 기존 `~/.codex/config.toml`이나 OpenCodex 연결 설정을 덮어쓰지 않습니다.
`.media-bridge-codex`에는 이 연결의 대화·상태가 저장될 수 있으므로 Git에 포함하지 않습니다.
API Key를 위 명령에 넣지 않습니다. Provider 키는 Media Bridge가 보유합니다.

이미지 첨부 시 마지막 질문 앞에 `--image ./screenshot.png --`를 추가합니다.
마지막 `--`는 질문문을 이미지 파일 인수와 구분합니다.
파일 수정이 필요한 작업은 해당 전용 작업 폴더에서 `--sandbox workspace-write`를 선택합니다.
승인·sandbox를 우회하는 옵션은 사용하지 않습니다.

## 지원 범위와 제한

- 함수 정의·호출 ID·인자·실행 결과, namespace 함수 이름 변환을 지원합니다.
- 텍스트와 함수 인자 SSE를 upstream에서 받은 순서로 전달합니다.
- 개인 runtime은 과거 사용자 메시지의 이미지도 같은 OCR gate로 변환합니다.
  현재는 요청마다 OCR이 재실행될 수 있어 실제 서비스 사용량이 발생할 수 있습니다.
- OCR 실패 시 LLM에 원본을 보내지 않고 차단합니다.
- OpenAI hosted 웹검색과 custom 도구는 지원하지 않습니다. 웹검색은 위처럼 client에서 명시적으로
  끄며 Media Bridge가 입력 도구를 조용히 삭제하지 않습니다. OpenAI Vision 토큰은 요구하지 않습니다.
- 서버 `previous_response_id`에 의존하는 도구 이력 복원, 도구 결과 자체에 첨부된 이미지,
  실제 namespace 하위 agent 생성·실행은 검증 범위 밖입니다.
- WSL 합성 OCR/LLM으로 실제 CLI 이미지 입력·파일 수정·도구 결과·세션 후속 질문을 검증했습니다.
  이것은 실제 Solar의 도구 선택 품질, Document Parse 인식 정확도, 공개 설치 검증을 대신하지 않습니다.

## 연결 해제

전용 Codex 실행을 종료합니다. 위 명령의 환경변수는 그 실행에만 적용되므로 평소 방식으로
Codex를 실행하면 기존 설정을 사용합니다. 전용 대화 기록을 유지하려면 `.media-bridge-codex`를
보존합니다. 기록 삭제는 사용자 선택이며 Media Bridge 제거와 함께 자동으로 삭제하지 않습니다.

Media Bridge 자체의 중지·제거는 [npm CLI 매뉴얼](npm-cli.md)을 따릅니다.
공식 설정 참고: [Codex 설정 레퍼런스](https://learn.chatgpt.com/docs/config-file/config-reference).
