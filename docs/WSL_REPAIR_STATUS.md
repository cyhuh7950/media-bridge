# WSL 설정 화면 복구 작업현황

- 담당: 어울 / codex/openai-models-contract
- 원인: npm CLI는 config.json 부재 시 기본값으로 시작하지만 Python 설정 화면은 파일을 필수로 요구함.
- 변경: 파일이 없으면 초기 화면 기본값 사용. 손상된 파일 검사 유지. 빈 instructions는 추가 지시 없음으로 처리.
- 검증: 수정 전 3 실패/20 통과, 수정 후 관련 테스트 38 통과. Ruff 및 mypy 통과.
- 배포: WSL Git worktree에서 빌드 후 runtime 표준 경로 교체 예정. 기존 실행본 하나만 복구용 유지.
- 미검증: WSL 사용자 API 키 저장 및 외부 LLM/OCR 응답. 키 복사 또는 추정하지 않음.

## 배포·정리 결과
- WSL c92f01f 빌드 SHA256: 5bb66539c4618aec28bb38b2a2410d423f908915288eda5551611db22afe7cf9.
- 현재 경로: /home/daon/.media-bridge/runtime/bin/media-bridge-runtime.
- 복구용: runtime.previous/bin/media-bridge-runtime (69f7f84).
- 최초 settings GET 값을 그대로 POST한 시험은 필수 conversion 설정 누락으로 400. 설치 CLI의 완전한 defaultConfig로 POST하여 200, config.json 생성·0600 확인.
- 로그인 쉘 재시작 후 /, /health, /api/settings 모두 200.
- 빈 instructions 요청은 guard 거부 대신 인증정보 없음 응답: guard 결함 해소 확인. 외부 Provider 성공은 미검증.
- runtime-32d5b91, runtime-bfb6dc7, runtime-556f538, runtime.backup-32d5b91 제거. 69f7f84는 runtime.previous로 보존.
- 이번 WSL Git 빌드 worktree 및 확인된 이전 임시 소스·빌드·artifact·venv 정리 완료.
- ysna-server는 이번 복구에서 변경하지 않음.
