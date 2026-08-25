# Media Bridge Core, MCP Interface, Gateway API

Core는 media detector, acquisition, OCR/Vision/parser, sanitizer, cleanup과 fail-closed 결정을 소유한다.
MCP Interface는 `extract_image_context`, `analyze_error_image`, `prepare_for_model`을 제공하지만 자동 interception
기능은 없다. Gateway API와 Adapter가 실제 target model이 정해진 뒤 pre-request gate 순서를 강제한다.
Non-Vision downstream은 성공한 text-only payload와 original media 0개가 확인되기 전 호출할 수 없다.

Provider/model capability 정본은 외부 router가 소유할 수 있고 Media Bridge는 signed snapshot을 방어적으로
검증한다. transformation backend capability와 provenance는 Media Bridge 책임이다.
