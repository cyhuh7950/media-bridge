# WSL 설정 화면 복구 작업현황

- 담당: 어울 / codex/openai-models-contract
- 원인: npm CLI는 config.json 부재 시 기본값으로 시작하지만 Python 설정 화면은 파일을 필수로 요구함.
- 변경: 파일이 없으면 초기 화면 기본값 사용. 손상된 파일 검사 유지. 빈 instructions는 추가 지시 없음으로 처리.
- 검증: 수정 전 3 실패/20 통과, 수정 후 관련 테스트 38 통과. Ruff 및 mypy 통과.
- 배포: WSL Git worktree에서 빌드 후 runtime 표준 경로 교체 예정. 기존 실행본 하나만 복구용 유지.
- 미검증: WSL 사용자 API 키 저장 및 외부 LLM/OCR 응답. 키 복사 또는 추정하지 않음.
