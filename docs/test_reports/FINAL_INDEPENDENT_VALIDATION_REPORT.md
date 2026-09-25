# Media Bridge 독립 품질검증 최종 보고서 (9차 — main 정본 전환, 추론 등급 릴리스(0.1.14), Enterprise Web Console 재검증)

검증자: 독립 QA(개발 담당자와 별개). 검증일: 2026-09-25. 이 보고서는 동일 경로의 8차 보고서를 **대체**한다.

## 0. 이번 라운드 핵심 변경 요약

8차(2026-09-06) 이후 약 3주간 개발이 계속됐다. 가장 큰 구조적 변화는 **정본 checkout 자체가 바뀐 것**이다.

| 항목 | 8차 시점 | 9차(이번) 시점 |
|---|---|---|
| `D:\Project\Media-Bridge` 브랜치 | `codex/media-bridge`(dirty, 23건 미커밋) | **`main`(clean, `origin/main`과 완전 일치)** |
| HEAD | `2a2ff5c` | `9933dd2`(`docs: record Media Bridge 0.1.14 public release`) |
| npm 패키지 | `@cyhuh/media-bridge@0.1.13` | `@cyhuh/media-bridge@0.1.14`(당일 공개) |
| `docs/superpowers` | main에서 제외됨(정책) | **main에 재도입**(`llm-reasoning-effort`, `omniroute-compatible-model-routing`, `npm-installed-reasoning-release` 관련 신규 설계·계획) |
| Enterprise Control Plane | 로컬 코드만 존재 | `WORK_STATUS`에는 `ysna-server` 배포 기록이 있음. 이번 독립 검증은 live 서비스 상태를 확인하지 않음 |

이번 라운드는 **정본 자체가 바뀌었으므로**, 이전 8차까지의 결함 추적 번호(DEF-08~DEF-17)를 그대로 이어가지 않고 이번 검증에서 새로 발견한 사항을 독립적으로 번호를 매겨 기록한다. 8차까지의 이력은 §7에 요약 인용한다.

## 1. 검증 목적과 범위

`main`(`9933dd2`)을 기준으로 (1) 신규 LLM 추론 등급 기능, (2) 사용자 매뉴얼과 실제 동작 간 정합성, (3) 이번 라운드에서 실행한 로컬 테스트 묶음을 독립 검증한다. `ysna-server` 운영 상태는 이번 라운드에서 접속·검증하지 않았으며, 이 보고서는 로컬 근거와 live 상태를 구분한다.

## 2. 기준 자료와 정본 판정

- **정본 브랜치**: 검증 시작 시 `main` HEAD `9933dd2`와 `origin/main`이 일치했고 작업 트리는 clean이었다고 실행 기록에 남아 있다. 이 보고서는 검증 결과를 정리한 미추적 산출물이므로, 보고서 작성 후 현재 작업 트리 상태와 검증 시작 상태를 혼동하지 않는다.
- **설계서**: `docs/superpowers/specs/2026-09-24-npm-installed-reasoning-release-design.md`(npm 후보 배포 절차), `docs/superpowers/specs/2026-09-22-llm-reasoning-levels-design.md`(추론 등급 기능 자체, "상태: 설계 초안"). `docs/design/DESIGN.md`도 존재하나 이번 라운드에서는 보조 참고로만 사용했다(범위 밖 세부 미검토).
- **계획서**: `docs/superpowers/plans/2026-09-24-npm-installed-reasoning-release.md`, `docs/superpowers/plans/2026-09-23-omniroute-compatible-model-routing.md`. OmniRoute 계획의 branch 제약은 작업 지침이지 현재 `main`의 구현·병합 상태를 증명하는 Git 근거가 아니다. 해당 기능의 상태는 이번 라운드에서 독립 확인하지 않았다(§4.4).
- **작업현황**: `docs/WORK_STATUS.md`(517줄, 2026-09-19~2026-09-25 구간). 개발자 자체 기록이며 독립 검증의 근거로 대체하지 않는다.
- **AGENTS.md**: 저장소 전체에서 검색했으나 존재하지 않는다(1차 라운드부터 9차까지 일관).
- 이번 검증 중 웹 콘솔 검증을 위해 `web/`에서 `npm install`을 1회 실행했다(package.json에 선언된 `qrcode` 의존성이 `node_modules`에 누락돼 있어 기존 테스트 파일 1개가 즉시 실패했기 때문 — §6 TC-WEB-01). 이는 이미 `package-lock.json`에 선언된 의존성을 설치한 것으로, 제품 소스·설정 파일은 변경하지 않았다.

## 3. 실행 환경

| 항목 | 값 |
|---|---|
| 검증 경로 | `D:\Project\Media-Bridge`(검증 시작 시 main `9933dd2`, clean이라고 기록; 별도 worktree 없이 직접 검증) |
| Python(.venv) | 3.13.9(저장소 내 `.venv` 재사용) |
| Node.js | v24.18.0 |
| npm registry | `@cyhuh/media-bridge@0.1.14` 공개 확인 |
| Docker CLI / PostgreSQL | 여전히 없음(1~9차 동일 환경 제약) |
| Enterprise `ysna-server` 실제 운영 서버 | 이번 라운드에서 접속하지 않아 live 배포 상태 미확인 |
| 사전 존재 프로세스 | python.exe 0개(시작 시점), node.exe 60여 개가 이미 실행 중이었으나 명령행 대조 결과 이 프로젝트와 무관함을 확인(다른 개발 도구·확장 프로세스로 추정) |

## 4. 설계 요구사항 대비 구현 충실도 매트릭스

### 4.1 신규 — LLM 추론 등급(reasoning effort) 설정, 설치형(Local)

| 요구사항(설계서 근거) | 구현 위치 | 실행 근거 | 판정 |
|---|---|---|---|
| 두 단계 설정 UI·저장: Media Bridge 기본(`reasoningEffort`)과 LLM 값(`textLlm.reasoningEffort`) | `media_bridge_personal/npm_runtime.py` | 브라우저에서 두 selector와 전역 `high` 저장 후 `/api/settings` 응답을 확인했다. personal API 회귀는 두 필드 저장 및 기본값도 검사한다. 브라우저에서 LLM 고정값을 바꿔 저장하는 동작은 별도로 실행하지 않았다(§6 TC-REASON-01). | **부분 충족**(브라우저 전역 설정 확인, LLM 필드 저장은 테스트 근거) |
| LLM 명시값은 전역값보다 우선하고 `provider_default`는 Media Bridge 기본값을 사용 | `_effective_reasoning_effort()`, ProviderTester | mock transport 회귀에서 전역 `low` + LLM `high`일 때 downstream payload `high`, 전역 `medium` + LLM `provider_default`일 때 payload `medium`을 확인했다(`tests/personal/test_npm_runtime.py`, `test_real_provider_tester_runs_ocr_then_text_without_forwarding_media`, `test_provider_tester_uses_media_bridge_effort_when_llm_effort_is_unset`). 실제 Provider 응답은 호출하지 않았다. | **모의 요청 계약 충족**, 실제 Provider 적용 미검증 |
| 지원 선택은 Provider/API/모델 교집합으로 제한하고 미지원 조합은 거부 | `npm_runtime.py`의 `syncReasoning()`, `/api/reasoning-options` | 코드 및 personal API 회귀에서 옵션·거부 응답을 확인했다. 독립 브라우저 세션에서 해당 endpoint를 직접 호출한 결과는 기록되지 않았다. | **부분 충족**(회귀 테스트 근거, 브라우저 API 호출 미실시) |
| Provider 기본값에서는 provider-specific reasoning 필드를 추가하지 않음 | downstream adapter | 실제 Provider 요청은 범위 밖이었다. 보고서에는 모의 요청에서 해당 설정의 필드 부재를 별도로 확인한 증거가 없다. | **부분 충족**(코드·회귀 근거, payload 부재 실측 미검증) |
| 설정 저장은 기존 config.json 포맷과 호환, 필드 없는 기존 설정도 정상 로드 | `defaultConfig()`/`_normalize_npm_config()` | `tests/personal` 그룹 실행(§6 TC-PY-GROUP)에 포함된 회귀로 확인 | **충족** |

### 4.2 npm CLI 배포 계층(8차까지 검증분, 재확인)

| 항목 | 결과 |
|---|---|
| npm registry 공개 상태 | `@cyhuh/media-bridge@0.1.14`, `latest` dist-tag 확인(재확인, §6 TC-EXT-01) |
| Node 계약 시험 | `node --test tests/npm/*.test.cjs` → **87 tests, 83 passed, 4 skipped, 0 failed**(work-status.md의 "83 passed, 4 skipped" 기록과 정확히 일치) |
| DEF-13/DEF-16(과거 라운드에서 발견·수정 확인한 Windows tar/Conda 차단) | 이번 라운드에서 재확인하지 않음(범위상 새 기능 우선, 이전 라운드에서 이미 코드 레벨로 반복 확인됨. 회귀 여부는 §10 미검증 범위에 기록) |

### 4.3 확인된 동작 — `mb init`/일부 `mb start` 경로에서 사용자 로그인 자동 시작을 등록

- **코드 근거**: `packaging/npm/bin/mb.cjs`에서 `init()`은 자동 시작을 직접 등록하고, `start()`는 service marker가 활성 상태가 아니면 `ensureAutostart()`를 통해 등록한다. Windows는 현재 사용자 로그인 작업을 만들고, 실패하면 사용자 Startup 폴더에 `.cmd`를 쓴다. Linux는 사용자 systemd 또는 profile 경로를 사용한다. 이 경로에는 별도의 자동 시작 동의 prompt/flag가 없다.
- **매뉴얼 비교**: `docs/manuals/user/npm-cli.md`와 `docs/install/windows.md`는 `mb service install`을 재부팅 후 자동 시작을 설정하는 절차로 안내한다. 따라서 **코드와 현재 매뉴얼 설명 간 불일치**는 확인된다.
- **실측 범위**: 실행 기록에는 격리 HOME에서 `mb init` 후 `windows-startup` 파일이 생성되고 실제 사용자 Startup 경로 및 `schtasks /Query`에는 항목이 없었다고 적혀 있다. 다만 §6 절차에는 Windows의 `os.homedir()`에 영향을 주는 `USERPROFILE` 등 전체 격리 환경이 기록되지 않아 재현성 근거를 보완해야 한다. `mb start` 단독의 깨끗한 service marker 시나리오는 별도로 실측하지 않았다.
- **판정 한계**: 보고서가 인용한 `2026-09-01-media-bridge-npm-ux-design.md`는 현재 저장소에 없으므로 승인된 설계 정본으로 독립 확인할 수 없다. 따라서 **설계 위반**이라고 단정하지 않고, 확인 가능한 사실을 코드와 매뉴얼 간 불일치로 한정한다.
- **영향/심각도**: 사용자 계정 범위의 로그인 자동 시작 설정이며, 이 증거만으로 시스템 전체 서비스 설치나 관리자 권한 변경이라고 볼 수 없다. 영향은 제품의 의도된 기본 동작과 사용자 기대에 달려 있고, 보고서에는 심각도 기준표가 없다. 따라서 `높음`은 확정하지 않고 **등급 미확정**으로 둔다.
- **후속 결정**: 제품 의도에 따라 자동 시작을 `mb service install`에만 두거나, 현재 `init`/`start` 동작을 유지하면서 매뉴얼과 사전 안내를 일치시키는 선택이 필요하다. 이 보고서는 제품 동작을 임의로 선택하지 않는다.

### 4.4 OmniRoute-compatible model routing — 이번 라운드 미검증

- 계획서의 branch 제약과 과거 `WORK_STATUS`는 작업 당시 상태를 기록할 뿐, 검증 기준 HEAD의 코드 부재나 현재 병합 상태를 증명하지 않는다.
- 이번 라운드에서는 public model/API/Gateway 구현을 `main` 전체에서 대조하거나 실제 흐름을 실행하지 않았다. 따라서 판정은 **NOT RUN / 구현 상태 미확인**이며, `미병합` 또는 `미구현`으로 단정하지 않는다.

## 5. 사용자 매뉴얼 대비 실제 동작 충실도 매트릭스

| 매뉴얼 | 서술 | 실제 확인 | 판정 |
|---|---|---|---|
| `docs/manuals/user/npm-cli.md` "자동 시작" 절 | `service install`이 재부팅 후 자동 시작을 등록한다고 안내 | 코드에서는 `mb init`이 등록하고 `mb start`도 marker가 없으면 등록함(§4.3). 안내와 실제 동작이 다름 | **불일치 확인, 의도 미확정** |
| `docs/install/windows.md` "재부팅 후 자동 시작" 절 | `mb service install`을 실행하라고 안내 | 코드 경로와 안내가 다름(§4.3). Windows 동작의 사용자 계정 범위 및 동의 흐름에 대한 독립 실측은 제한적 | **불일치 확인, 의도 미확정** |
| `docs/manuals/user/external-test.md` | `@cyhuh/media-bridge` 패키지명, 사전조건·증거 기록 항목 | 실제 registry 패키지명과 정확히 일치(§6 TC-EXT-01) | **정확** |
| `docs/manuals/user/connect-and-test.md`(8차에서 검증한 4열 카드 콘솔) | 4열 카드, 버튼명, 포트 8642 | 이번 라운드에서는 재확인하지 않았으나 코드(`npm_runtime.py`)에 해당 레이아웃이 그대로 유지돼 있음을 확인(구조적 회귀 없음) | **정확(재확인 근거는 8차 수준 유지)** |

## 6. 테스트 시나리오별 실행 결과

### TC-EXT-01(재확인) — npm registry 조회
- 실행: `npm view @cyhuh/media-bridge --json`
- 결과: 버전 0.1.4~0.1.14, `latest=0.1.14`
- 판정: **PASS**

### TC-N24(재확인) — npm Node 계약 시험
- 실행: `node --test tests/npm/*.test.cjs`
- 결과: **87 tests, 83 passed, 4 skipped, 0 failed**
- 판정: **PASS**(개발자 자체 보고와 일치)

### TC-PY-GROUP(그룹별 실행, 8차 방법론 재사용) — Python 시험
PostgreSQL이 필요한 그룹은 이번 환경에서 완주하지 못했거나 실행하지 못했다. 실행 완료한 그룹과 분리해 기록한다.

| 그룹 | 명령 | 결과 |
|---|---|---|
| unit+contracts+conformance+contracts_v2 | `pytest tests/unit tests/contracts tests/conformance tests/contracts_v2` | **125 passed** |
| adapters+gateway+integration | `pytest tests/adapters tests/gateway tests/integration` | **167 passed** |
| interop_v2+security | `pytest tests/interop_v2 tests/security` | **43 passed** |
| control/unit | `pytest tests/control/unit` | **65 passed** |
| packaging | `pytest tests/packaging` | **83 passed, 7 skipped**(Docker 미설치로 명시적 skip) |
| personal | `pytest tests/personal` | **59 passed** |
| **합계** | | **542 passed, 7 skipped** |

개별 실행 결과 합계는 **542 passed, 7 skipped**다. 보고서는 별도로 `597 tests collected`, control/security 5, control/integration 42라고 기록하지만 그 합은 596이므로 전체 collection 총계는 조정 전까지 미확정이다. 이 실행 묶음의 개별 PASS는 유지하되 Python 전체 결과를 총계 PASS로 단정하지 않는다.

### TC-DB-HANG(관측) — `tests/control/security` 실행이 제한 시간 동안 응답하지 않음
- 목적: PostgreSQL이 없는 환경에서 DB 의존 시험이 어떻게 실패하는지 확인
- 실행: `pytest tests/control/security`(60초, 120초 타임아웃 각각 시도), 이후 파일 4개를 개별로 15초씩 재시도
- 기대 결과: 연결 거부 등으로 빠르게 실패(다른 회차의 DB 의존 시험처럼)
- 실제 결과: 기록상 4개 파일 각각 15초, 전체 시도는 60/90/120초 제한에서 출력이 없었다. 이는 **해당 제한 시간 동안 진행 결과가 관측되지 않았음**을 뜻하며, 영구적인 무한 대기나 정확한 정지 지점까지 입증하지는 않는다.
- 판정: **BLOCKED(실행 환경/진단 미완료)**. PostgreSQL 부재는 환경 사실이지만, 무응답의 직접 원인이 fixture인지, collection/import인지, 연결 대기인지는 stack/verbose 증거가 없어 확정하지 않는다.
- 영향/심각도: 현재 증거로 제품 결함 또는 fixture 설계 결함을 확정할 수 없다. 로컬 검증이 제한 시간 내 끝나지 않은 관측 사실로 기록한다.
- 후속 조치 권고: 먼저 verbose/no-capture 실행 또는 hang stack을 확보해 멈춘 단계를 찾고, DB 연결 timeout이 원인일 때에만 bounded timeout을 검토한다. 필수 통합 테스트를 무조건 skip시키지는 않는다.

### TC-CTRL-INT(BLOCKED, 확인만) — `tests/control/integration`
- `pytest tests/control/integration --collect-only` → **42 tests collected**(수집은 정상, 실행은 PostgreSQL 필요)
- 판정: **BLOCKED**(환경). 이번 라운드에서는 실행하지 않았고, PostgreSQL 필요 여부를 전제로 대기한다. TC-DB-HANG과 같은 직접 원인이라고 확정하지 않는다.

### TC-REASON-01(신규) — 추론 등급 설정 실제 브라우저·API 검증
- 목적/연결 요구사항: §4.1 전체
- 선행조건: 기록상 격리 `HOME=D:\tmp\mb-reasoning-qa-20260925`, `MEDIA_BRIDGE_RUNTIME_COMMAND`를 저장소 `.venv` Python으로 지정(QA 소스 오버라이드, 실제 registry 다운로드 경로는 검증하지 않음). Windows `os.homedir()` 격리에 쓰인 `USERPROFILE` 등 전체 환경값은 실행 기록에 남아 있지 않다.
- 실행 절차: `mb init` → `mb start --port 8781` → 브라우저로 `http://127.0.0.1:8781/` 접속 → "기본 추론 등급"을 `높음`으로 변경 → "설정 저장" 클릭 → `curl http://127.0.0.1:8781/api/settings`로 저장값 확인 → `mb stop`
- 실제 결과: 화면에 두 selector가 렌더링됐고, 전역 등급 `high` 저장 후 `GET /api/settings`가 이를 반환했다. 이 브라우저 시나리오는 Non‑Vision LLM 고정값을 직접 변경하지 않았다. 우선순위는 personal mock-transport 테스트에서 별도로 확인됐다(§4.1).
- 판정: **PASS(전역 UI 저장 시나리오 한정)**. 실제 npm registry 설치와 실 Provider 적용은 미검증이다.
- 부수 발견: §4.3(자동 시작 코드와 매뉴얼 간 불일치; 승인 설계 위반 여부는 미확정)

### TC-WEB-01(신규) — Enterprise Web Console(React) 단위·정적 검사
- 목적: 8차에서 미검증으로 남긴 Enterprise Web Console을 이번에 검증
- 선행조건: `web/node_modules`가 이미 존재했으나 `qrcode`/`@types/qrcode`가 누락돼 있어 `npm install`로 보완(§2)
- 실행: `npx vitest run` → 보완 전 **8/9 파일 통과, `App.test.tsx` 1개는 import 실패로 0 test**; 보완 후 **9/9 파일, 41 tests 전부 통과**(개발자 work-status.md의 "Vitest 41 passed (9 files)"와 정확히 일치)
- 추가: `npm run typecheck` → 오류 없음. `npm run lint` → 오류 없음. `npm run build` → `vite build` 성공(81 modules, gzip 97.6KB)
- 판정: **PASS**(보완 후). 보완 전 상태는 로컬 체크아웃의 `node_modules`가 `package-lock.json`과 동기화되지 않았던 환경 문제이지 소스 코드 결함이 아니다.

### TC-OMNI-01(NOT RUN) — OmniRoute-compatible model routing
- 판정: **NOT RUN**. 이번 라운드는 해당 기능 실행·코드 대조를 범위에 포함하지 않았다. 계획서와 과거 상태 기록만으로 기준 HEAD의 병합 여부를 단정하지 않는다(§4.4).
- 재개 조건: 기준 branch/commit의 실제 구현 상태를 Git과 코드에서 먼저 확인한 뒤 별도 검증 범위를 정한다.

### TC-ENT-LIVE(NOT RUN) — Enterprise Control Plane 실제 운영(`ysna-server`) 확인
- 판정: **NOT RUN**. 이번 독립 검증에서 운영 서버에 접속하지 않았으므로 현재 배포 상태는 이 보고서가 확인하지 않는다. 과거 배포 기록은 `WORK_STATUS` 증거와 구분한다.
- 재개 조건: 별도 운영 검증을 수행할 담당자·범위·시간대를 확정하고, 승인된 read-only 확인 절차를 사용한다.

## 7. 발견 결함과 심각도

| ID | 심각도 | 내용 |
|---|---|---|
| DEF9-01(신규) | **미확정** | `mb init`과 marker가 없는 `mb start`가 사용자 로그인 자동 시작을 등록하는 코드가 있고 현재 매뉴얼 안내와 다름. 원 설계의 저장소 정본·심각도 기준은 확인되지 않음(§4.3, §5) |
| DEF9-02(신규 관측) | **미확정** | `tests/control/security` 4개 파일이 제한 시간 동안 응답하지 않았다는 실행 기록. PostgreSQL 부재가 직접 원인인지, fixture/collection hang인지 증거가 부족함(§6 TC-DB-HANG) |
| (환경 보정) | — | 검증 전 `qrcode`/`@types/qrcode` 누락이 관측돼 `npm install` 후 Web suite를 재실행했다. 현재 `package.json`/lock 근거와 node_modules 상태는 구분하며, 이 결과만으로 깨끗한 lockfile install 환경을 입증하지 않는다. |
| (8차까지 이력) | — | DEF-08/09/11/13/15/16(PID 소유권, 패키지 scope, Windows tar, runtime artifact E2E, Conda 차단, npm registry 공개)은 8차에서 모두 해소 확인됨. 이번 라운드에서 재검증하지 않았으므로 회귀 여부는 §10 미검증 범위로 남긴다 |

## 8. 회귀 위험

- `main`의 이력은 8차 검증 기준과 달라졌고, 이번 라운드에서 DEF-13/DEF-16(Windows tar, Conda 차단) 코드를 재검증하지 않았다. 따라서 회귀 여부와 가능성은 이 보고서에서 평가하지 않는다(§4.2, §10).
- `WORK_STATUS`에는 GitHub PR 생성의 collaborator 권한 오류가 기록돼 있다. 이 오류만으로 PR 없이 main에 반영한 커밋이 있었다고 결론낼 수 없으며, 본 보고서는 PR 메타데이터·커밋별 통합 경로를 대조하지 않았다. 따라서 이 증거만으로 거버넌스 위반이나 위험을 판정하지 않는다.
- Enterprise Control Plane의 여러 최근 수정(Provider Secret 비표시, 한글 이름 검증, 관리자 감사 필드 등)은 로컬 웹 테스트만으로 검증됐고, PostgreSQL migration integration은 로컬에서 반복적으로 "정체되어 미검증"으로 기록돼 있다. 이 패턴이 실제 `ysna-server` 배포 전 충분히 검증됐는지는 이번 세션에서 독립적으로 확인할 수 없다(§10).

## 9. 실행 결과 집계

서로 다른 단위인 자동화 테스트, 수동 시나리오, registry 조회, typecheck/lint/build는 하나의 PASS 숫자로 합산하지 않는다.

| 검증 묶음 | PASS | SKIP | BLOCKED/미완료 | 비고 |
|---|---:|---:|---:|---|
| Node 계약 테스트 | 83 | 4 | 0 | 87 tests |
| Python 실행 그룹 | 542 | 7 | 47 | 597 collected라고 기록했으나 `542 + 7 + 47 = 596`; 1건 미조정 |
| Web Console Vitest | 41 | 0 | 0 | typecheck, lint, build는 별도 각 PASS |
| 보조 검증 | 별도 표기 | — | — | registry 조회 1회와 브라우저 전역 설정 시나리오 1회는 테스트 케이스 수에 합산하지 않음 |
| OmniRoute / 운영 서버 | — | — | NOT RUN 2개 | §6에 각 사유와 미검증 범위 기재 |

전체 test-case 총계는 Python 1건의 출처가 확인될 때까지 확정하지 않는다. 아래 결과가 각 검증 묶음의 개별 실행 증거다.

## 10. 미검증 범위와 차단 사유

| 범위 | 차단 사유 | 재개 조건 |
|---|---|---|
| Enterprise Control Plane PostgreSQL 통합(보고서상 47건) | Docker/PostgreSQL 부재로 실행하지 못했거나 제한 시간 내 끝나지 않음. 총계 1건 차이 미조정 | collection 수와 개별 차단 대상을 다시 대조한 후 PostgreSQL 환경에서 실행 |
| `ysna-server` 실제 운영 상태 | 이번 검증에서 접근·확인하지 않음 | 별도 승인된 read-only 절차와 범위로 확인 |
| OmniRoute-compatible model routing | 이번 라운드에서 코드·실행 대조 미실시; main 포함 여부 미확인 | 기준 commit의 Git 이력 및 구현을 대조한 후 검증 범위 결정 |
| 실제 `npm install -g @cyhuh/media-bridge`(진짜 외부 설치) | 이번 라운드에서 시도하지 않음(8차에서 사용자가 보류를 선택한 이후 재승인 요청 없음) | 사용자 승인 시 즉시 수행 가능 |
| DEF-13/DEF-16(Windows tar/Conda 차단) 수정의 `main`(9933dd2) 기준 회귀 재확인 | 이번 라운드는 신규 기능에 집중, 시간 배분상 생략 | 필요시 별도 요청으로 재실행 가능(코드 위치는 8차 보고서에 기록됨) |
| `/api/reasoning-options` 및 Provider별 downstream payload의 실제 호출 검증 | 실 Provider credential 필요, 승인 범위 밖 | 별도 승인 및 격리 credential 필요 |
| Enterprise Web Console의 E2E(Playwright) | 이번 라운드는 단위·정적 검사만 수행(시간 배분) | 별도 요청 시 `npm run test:e2e` 시도 가능(단, 실제 브라우저 기동 및 백엔드 필요) |

## 11. 수정·재검증 권고사항

1. **DEF9-01**: 먼저 제품 의도(자동 시작이 init/start의 기본 동작인지)를 확정한다. 그 다음에만 자동 시작 동작을 `service install`로 이동할지, 문서·사전 안내를 코드와 맞출지 결정한다. 현재 보고서 근거만으로 한쪽 구현을 선택하지 않는다.
2. **DEF9-02**: verbose/no-capture 실행이나 hang stack으로 멈춘 단계를 먼저 확인한다. DB 연결 대기가 원인으로 확인된 경우 bounded timeout을 검토하고, 필수 통합 테스트를 무조건 skip하지 않는다.
3. Enterprise Web Console 저장소의 `node_modules`가 `package-lock.json`과 어긋난 상태로 커밋/공유되지 않도록, CI에서 `npm ci`(lock 파일 엄격 설치)를 사용하는지 확인을 권고한다.
4. OmniRoute-compatible model routing은 branch·commit·코드 상태를 확인한 후 main 반영 여부와 추가 검증 필요성을 결정한다. 과거 PR 권한 오류만으로 현재 상태를 추정하지 않는다.
5. `main`이 정본으로 전환된 만큼, 다음 라운드부터는 이 checkout을 기준으로 계속 검증하고, DEF-13/DEF-16 등 과거 결함의 회귀 여부를 주기적으로 재확인할 것을 권고한다.

## 12. 독립 최종 판정

### **CONDITIONAL ACCEPTANCE (잠정)**(설치형 로컬 기능 + Enterprise Web Console의 제한된 로컬 검증 범위 한정)

사유:
- 추론 등급 설정의 전역 저장 UI/API 시나리오는 브라우저에서 확인했고, LLM 고정값 우선순위와 전역 fallback은 mock-transport 회귀 테스트 근거가 있다. 실제 npm registry 설치와 실제 Provider 적용은 확인하지 않았다. Enterprise Web Console은 41개 Vitest와 typecheck/lint/build가 통과했다고 기록돼 있다.
- DEF9-01은 코드와 현재 매뉴얼의 차이가 확인됐지만, 승인 설계 위반 여부와 심각도는 확정할 수 없다. 동작 의도 확인 전에는 제품 결함으로 단정하지 않는다.
- Control Plane PostgreSQL 통합은 미실행/제한 시간 내 미완료가 있으며, 보고서상 collected 숫자와 합산 결과도 1건 차이가 난다. 차단 원인과 총계는 미해결이다.
- `ysna-server` 실제 운영 상태와 OmniRoute 기능은 이번 라운드에서 확인되지 않았다. 이 보고서는 해당 항목의 현재 상태를 판정하지 않는다.
- 따라서 **CONDITIONAL ACCEPTANCE는 위에 명시한 로컬 검증만을 뜻하는 잠정 판정**이다. 수치 정합성, DEF9-01의 제품 의도, 실제 npm 설치 및 운영 경계의 확인을 제품 전체 acceptance로 확대하지 않는다.
- 이 판정은 **제품 전체(Enterprise Control Plane의 실제 운영 배포, OmniRoute routing 포함)의 ACCEPTED를 의미하지 않는다.**

## 13. 검증 증거와 관련 파일 목록

- 실행 로그 근거:
  - `npm view @cyhuh/media-bridge --json` → `latest=0.1.14`
  - `node --test tests/npm/*.test.cjs` → `tests 87, pass 83, fail 0, skip 4`
  - `pytest tests/unit tests/contracts tests/conformance tests/contracts_v2` → `125 passed`
  - `pytest tests/adapters tests/gateway tests/integration` → `167 passed`
  - `pytest tests/interop_v2 tests/security` → `43 passed`
  - `pytest tests/control/unit` → `65 passed`
  - `pytest tests/packaging` → `83 passed, 7 skipped`
  - `pytest tests/personal` → `59 passed`
  - `pytest tests/control/security`(보고서 기록: 전체 60/90/120초 제한 시도, 파일별 각 15초) → 제한 시간 내 출력 없음. hang 지점 미확인(TC-DB-HANG)
  - `pytest tests/control/integration --collect-only` → `42 tests collected`
  - 실제 CLI 시연: `mb init`(자동 시작 등록 로그 확인) → `mb start --port 8781` → 브라우저에서 전역 등급 저장 → `curl /api/settings`에서 `reasoningEffort: high` → `mb stop`. Runtime은 저장소 `.venv` Python override였으므로 npm 공개 artifact의 다운로드·설치는 미검증.
  - `schtasks.exe /Query /TN "Media Bridge"` → 실제 시스템에는 없음(격리 확인) / 격리 `HOME`에는 `Media Bridge.cmd` 생성 확인
  - `web`: `npx vitest run`(보완 전 8/9, 보완 후 9/9, 41 tests) / `npm run typecheck` / `npm run lint` / `npm run build`
- 대조한 설계·계획: `docs/superpowers/specs/2026-09-22-llm-reasoning-levels-design.md`, `docs/superpowers/specs/2026-09-24-npm-installed-reasoning-release-design.md`, `docs/superpowers/plans/2026-09-23-omniroute-compatible-model-routing.md`
- 대조한 매뉴얼: `docs/manuals/user/npm-cli.md`, `docs/install/windows.md`, `docs/manuals/user/external-test.md`, `docs/manuals/user/connect-and-test.md`
- 대조한 작업현황: `docs/WORK_STATUS.md`(517줄, 2026-09-19~2026-09-25 구간)
- 대조한 소스: `packaging/npm/bin/mb.cjs`(자동 시작 등록 로직), `media_bridge_personal/npm_runtime.py`(추론 등급 UI·API)
- 8차 보고서의 발견 사항은 §0·§4.2·§7에서 요약 인용했다(동일 파일 경로 덮어쓰기로 원문은 보존되지 않음).
- 이번 검증 중 제품 코드·설계서·매뉴얼은 수정하지 않았다고 기록돼 있다. `web/`에서 `npm install`을 실행했고 package manifest의 변경 여부는 현재 Git diff로 확인한다. 보고서 작성자는 격리 임시 디렉터리와 프로세스 정리, 실제 시스템 Startup/작업 스케줄러 무영향을 확인했다고 기록했으나, 첨부 실행 로그가 없어 이 최종 보고서에서 독립 재현한 증거와 동일시하지 않는다.
