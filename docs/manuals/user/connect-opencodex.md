# OpenCodex 연결 상태 안내

현재 OpenCodex Adapter는 `2.28.0` exact source extension과 Media Bridge 설정 fragment까지
코드 검증된 상태다. 일반 설치 프로그램이나 자동 연결 화면은 아직 제공하지 않으며, 설치된
OpenCodex 원본에는 자동 적용되지 않는다.

연결이 적용된 환경에서는 이미지가 포함된 Non-Vision 요청이 모델 호출 전에 텍스트로 변환된다.
변환·sanitizer·cleanup 또는 capability 확인이 실패하면 요청은 차단되지만 실패한 response item을
세션에 남기지 않아 이후 텍스트 대화를 계속할 수 있도록 설계됐다.

현재 단계에서 사용자가 직접 source·설정 파일을 변경하는 것은 권장하지 않는다. P5 설치 bundle과
실제 환경 검증이 완료되기 전에는 운영 연결 완료로 간주하지 않는다.
