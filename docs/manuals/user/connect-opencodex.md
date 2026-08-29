# OpenCodex 연결 상태 안내

현재 OpenCodex Adapter는 `2.28.0` exact source extension과 Media Bridge 설정 fragment까지
코드 검증된 상태다. 개인용 Web 화면에서 endpoint·model·credential 환경변수 이름 metadata를 저장할 수 있으며,
설치된 OpenCodex 원본 설정에 자동으로 덮어쓰지는 않는다.

연결이 적용된 환경에서는 이미지가 포함된 Non-Vision 요청이 모델 호출 전에 텍스트로 변환된다.
변환·sanitizer·cleanup 또는 capability 확인이 실패하면 요청은 차단되지만 실패한 response item을
세션에 남기지 않아 이후 텍스트 대화를 계속할 수 있도록 설계됐다.

현재 단계에서 사용자가 직접 source·설정 파일을 변경하는 것은 권장하지 않는다. P5 설치 bundle과
실제 환경 검증이 완료되기 전에는 OpenCodex 연결 완료로 간주하지 않는다.
