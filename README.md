# Non-Vision Media Bridge

이미지와 PDF가 포함된 요청을 대상 모델 호출 전에 판정하고, Non-Vision 모델에는
OCR·Vision 설명으로 변환된 텍스트만 전달하는 fail-closed pre-request gate입니다.

이 저장소는 MCP 도구와 함께 강제 router adapter를 제공합니다. 안전성은 모델이
`prepare_for_model` 호출을 선택하는지에 의존하지 않습니다.

현재 작업 브랜치는 개발·테스트 전용입니다. 서비스 등록, 방화벽, reverse proxy,
원격 배포는 포함하지 않습니다.
