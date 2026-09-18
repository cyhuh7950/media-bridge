# Media Bridge 작업현황

판정: RUNNING
정본: `docs/design/DESIGN.md`, `docs/WORK_PLAN.md`, 현재 worktree `D:/Project/Media-Bridge/.worktree/auth-totp-recovery-email`
작업계획: S3 Provider catalog — 순수 카탈로그 계약 구현 완료, API·DB·Console 연결은 다음 작업
Git: `codex/auth-totp-recovery-email` / HEAD 확인 필요 / 기존 `.pr-body.md` untracked 보존 / 단일 writer 어울
최근 완료 증거: TOTP QR·Provider 선택 우회 흐름의 기존 구현과 배포형 Control Plane 문서를 확인함. 2026-09-19 OmniRoute 공급자 화면에서 API 키 호환 1/1, API 키 Provider 5/230, Image Providers 0/8, Local Providers 0/14 및 OpenAI/Anthropic 호환 추가 기능을 확인함.
현재 변경: `media_bridge_control/provider_catalog.py`, `tests/control/unit/test_provider_catalog.py`, 문서 갱신. 기존 `.pr-body.md`는 삭제하지 않음.
실행·검증 결과: Provider catalog RED에서 `ModuleNotFoundError` 확인 후 구현. catalog 단위 테스트 4 passed, ruff check 통과. API·DB·Console·배포 검증은 미실행.
오류와 조치: 없음.
미검증·승인 경계: 공개 OpenAI/Anthropic 계약, API key·tenant, DB migration, N:N routing, 비용·모니터링, OmniRoute 배포형 연결은 설계 승인 전 미구현·미검증. 인증·권한·Secret·비용·지속 schema 변경은 별도 승인 대상.
정확한 다음 조치: catalog를 Control API·Provider schema에 연결하고 분석/LLM kind와 Secret reference를 migration 없이 우선 계약 테스트로 확장한다.

## 2026-09-18 — 배포형 범위 초안

- 신산님 결정: 설치형과 구분되는 배포형은 외부 Endpoint, 사용자별 API key, 분석 Provider와 Non-Vision LLM Provider, N:N routing, 비용·분석·모니터링·감사 기능을 포함해야 한다.
- 결정된 기본 연결: 분석 Provider와 Non-Vision LLM Provider는 라우팅 프로필을 통한 N:N 연결이며 priority/fallback/health/cost 정책으로 자동 선택한다.
- 결정된 외부 연동: OmniRoute에는 설치형 localhost가 아니라 배포형 HTTPS Media Bridge Endpoint를 OpenAI 호환 Provider로 등록한다.
- 미결정: Anthropic 호환 세부 계약, OmniRoute의 tenant 헤더 전달 방식, 1차 Provider catalog의 최종 승인과 가격표 정책.
