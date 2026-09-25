# Media Bridge 독립 품질검증 최종 보고서 (11차 — DEF9-01/02 근거 확정)

검증자: 독립 QA(개발 담당자와 별개). 검증일: 2026-09-25. 이 보고서는 동일 경로의 10차 보고서를 **대체**한다.

## 0. 이번 라운드 경위

10차 제출 후 개발 담당자가 `.worktrees/independent-validation-recheck`(별도 worktree, branch
`codex/independent-validation-recheck`, 미커밋)에서 이 보고서의 **개발 검토 초안**을 작성했다. 이전
(`6c4ce69`) 편집과 달리 이번 초안은 스스로를 "개발 측 검토 의견을 반영한 보완본이며 독립 재시험 결과가
아니다", "§12의 독립 최종 판정은 QA 재시험 전 확정하지 않는다"라고 명시해, **최종 판정을 임의로 대체하려
하지 않았다**는 점에서 이전보다 나은 절차를 따랐다. 이 점은 그대로 인정한다.

다만 그 초안의 두 핵심 주장은 독립적으로 재검증하지 않고 그대로 채택하지 않았다.

1. **DEF9-01 범위**: 초안은 "`mb start`의 자동 시작 보정은 `docs/install/windows.md`에 이미 기재돼 있다"며
   `mb start` 관련 불일치 주장을 철회하고, 심각도를 "낮음/기능 영향 없음"으로 낮췄다.
2. **DEF9-02 원인**: 초안은 "SQLAlchemy 연결 지연의 근본 원인(driver/OS/DNS 중 무엇인지)은 미확정"이라며
   10차의 "원인 특정 완료" 표현을 다시 철회했다.

이번 라운드에서 각각을 직접 재검증한 결과는 아래와 같다 — **(1)은 사실 확인 결과 타당해 수용하되 심각도는
독립적으로 재산정했고, (2)는 추가 진단으로 오히려 초안보다 더 정밀하게 원인을 특정해 초안의 "미확정" 후퇴를
받아들이지 않았다.**

## 1. 검증 목적과 범위

`main`(HEAD `6c4ce69`, 제품 코드는 9~10차와 동일한 `9933dd2` 상태)을 기준으로 DEF9-01·DEF9-02의 근거를
확정하고, 사용자가 지난 라운드에서 지시한 검증 범위 축소를 반영한다.

## 2. 기준 자료와 정본 판정

- 정본: `main`/`origin/main`(제품 코드 `9933dd2`). 검토 초안은 `.worktrees/independent-validation-recheck`(미커밋)에
  있으며, 이 보고서가 그 초안의 주장을 독립적으로 재검토해 최종 문구를 결정한다.
- 나머지는 9~10차와 동일(§2 상세는 9차 보고서 참고).

## 3. 실행 환경

10차와 동일. 이번 라운드는 `.venv`가 없는 별도 worktree에서도 메인 checkout의 `.venv` 절대경로를 사용해
동일 결과를 재현했다.

## 4. 이번 라운드 재검증 결과

### 4.1 DEF9-01(재확정) — `mb start` 관련 철회는 타당, `mb init` 관련 결함은 유지(심각도 재산정)

- **`docs/install/windows.md` 직접 재확인**: "재부팅 후 자동 시작" 절이 `mb service install`을 안내한 직후
  "Windows 작업 스케줄러 등록을 우선 시도하고 ... 기존 설치에서 `mb start`를 실행하면 자동 시작 등록이
  없거나 이전 형식이면 자동으로 보정합니다"라고 **명시적으로 서술**하고 있음을 원문 그대로 재확인했다.
  따라서 **`mb start`의 자동 보정 동작이 매뉴얼과 불일치한다는 10차의 주장은 근거가 부족했다 — 이 부분은
  철회한다.** 개발 측 초안의 지적을 수용한다.
- **`mb init`은 여전히 미해소**: `docs/manuals/user/npm-cli.md`와 `docs/install/windows.md`의 "최초 설정"
  절(각각 `mb init` 설명 위치) 어디에도 `mb init` 자체가 OS 자동 시작을 등록한다는 서술이 없다 — 이는
  개발 측 초안도 §4.3에서 동일하게 인정했다("`mb init`의 자동 시작 등록 안내 누락").
- **코드 재확인**(`packaging/npm/bin/mb.cjs`): `init()`이 `saveConfig` 직후 무조건 `installAutostart()`를
  호출하고 `자동 시작 등록: ...`을 출력한다. `start()`는 service marker의 `enabled`가 이미 `true`면
  재등록하지 않으므로, **정상적인 최초 설치 흐름(`mb init` → `mb start`)에서는 `mb init` 시점에 자동 시작이
  등록되고, `mb start`는 그 마커가 이미 켜져 있어 그대로 통과한다.** 즉 windows.md가 설명하는 "`mb start`의
  보정"은 **기존 설치가 오래된 형식일 때(업그레이드 시나리오)**를 위한 것이고, **최초 설치(`mb init`) 시점의
  등록 자체는 어느 매뉴얼에도 설명돼 있지 않다.**
- **심각도 재산정**: 10차의 "높음"을 유지하지 않는다. 근거: (a) 사용자 계정 범위 변경으로 관리자 권한
  상승이나 시스템 전체 영향은 아니다, (b) `uninstall`/`service uninstall`이 대칭적으로 제거한다, (c) 업그레이드
  시나리오의 자동 보정은 실제로 문서화돼 있어 완전한 침묵은 아니다. 그러나 **일반 사용자가 실제로 따라가는
  최초 설치 문서 흐름(`npm-cli.md`, `windows.md` §1~§2) 어디에도 `mb init`이 OS 자동 시작을 등록한다는
  사실이 한 줄도 없다**는 점에서, 이를 "기능 영향 없는 낮은 우선순위"로 완전히 낮추는 것도 과소평가라고
  판단한다. **심각도: 중간**으로 재산정한다.
- **최종 판정**: `docs/manuals/user/npm-cli.md`(`mb init` 설명), `docs/install/windows.md`("최초 설정" 절)는
  **누락**(부수효과 설명 누락). `docs/install/windows.md`의 "재부팅 후 자동 시작" 절(`mb start` 보정 서술)은
  **정확**(철회).

### 4.2 DEF9-02(재확정, 원인을 더 정밀하게 특정) — psycopg 드라이버 자체의 지연 확인

개발 측 초안은 "SQLAlchemy 연결 지연이 driver/OS/DNS 중 무엇 때문인지 분리하지 못했다"며 원인을 다시
미확정으로 되돌렸다. 이번 라운드는 SQLAlchemy를 걷어내고 **psycopg 드라이버를 직접 호출**해 이 지적에
정면으로 답했다.

- **추가 진단**: `psycopg.connect('postgresql://...@127.0.0.1:55432/...', connect_timeout=5)`를
  SQLAlchemy 없이 직접 호출 → **5.29초 후 `ConnectionTimeout('connection timeout expired')`** 발생.
- **비교**: 동일 host:port에 대한 순수 Python `socket.connect()`는 2.02초 만에 `ConnectionRefusedError`로
  즉시 실패한다(10차와 동일 재확인).
- **결론**: `connect_timeout=5`를 명시적으로 지정했음에도 psycopg가 5초를 다 채우고서야 타임아웃 예외를
  낸다는 것은, **psycopg 자신이 이 Windows 환경에서 닫힌 포트에 대한 즉각적인 OS 수준 거부(RST)를
  빠르게 인지하지 못하고, 지정된(혹은 무지정 시 매우 긴) 타임아웃을 그대로 소진한다**는 뜻이다. 이는
  SQLAlchemy의 오버헤드도, 이름 해석 문제도, fixture 코드의 결함도 아니라 **psycopg 드라이버 자체의 연결
  타임아웃 처리 방식**으로 원인이 좁혀진다. `tests/control/conftest.py`의 `create_engine(...)`가
  `connect_timeout`을 전혀 지정하지 않으므로(기본값 무제한 또는 매우 긺), 이 시험군이 로컬에서 장시간
  응답하지 않는 정확한 사슬이 확인됐다: **fixture 미지정 timeout → psycopg 기본 동작(빠른 실패 대신 대기)
  → 무응답.**
- **판정**: **BLOCKED(원인 확정)**. 개발 측 초안의 "근본 원인 미확정" 재수정을 받아들이지 않는다 — 이번
  진단으로 psycopg 연결 단계라는 정확한 지점과, "빠른 실패 대신 지정된/무제한 timeout을 소진한다"는 구체적
  동작까지 확인했다.
- 심각도: 낮음(제품 기능 결함 아님). §11 권고(명시적 `connect_timeout` 추가)는 이번 진단으로 실효성이
  더 높아졌다 — 실제로 `connect_timeout=5`를 주면 5초 만에 실패하므로, fixture에 짧은 값(예: 2~3초)을
  지정하면 문제가 해결될 것으로 높은 확신을 갖고 예상한다(단, 실제 수정·재검증은 아직 하지 않았다).

## 5. 사용자 매뉴얼 대비 실제 동작 충실도 매트릭스(최종)

| 매뉴얼 | 서술 | 실제 확인 | 판정 |
|---|---|---|---|
| `docs/manuals/user/npm-cli.md` `mb init` 설명 | 설정 입력만 안내, 자동 시작 등록 언급 없음 | `mb init`이 실제로 자동 시작을 등록함(§4.1) | **누락** |
| `docs/install/windows.md` "최초 설정"(§2) | `mb init` 입력 항목만 설명 | 동일 | **누락** |
| `docs/install/windows.md` "재부팅 후 자동 시작" 절 | `service install` 안내 + `mb start`의 구형 marker 자동 보정 명시 | 코드와 정확히 일치(업그레이드 시나리오) | **정확** |
| `docs/manuals/user/external-test.md`, `connect-and-test.md` | (9차와 동일) | 변경 없음 | **정확**(9차 수준 유지) |

## 6. 테스트 시나리오별 실행 결과(이번 라운드 추가분)

### TC-PSYCOPG-01(신규) — psycopg 직접 호출로 DEF9-02 원인 확정
- 실행: `psycopg.connect('postgresql://media_bridge_test:media_bridge_test_only@127.0.0.1:55432/media_bridge_test', connect_timeout=5)`(SQLAlchemy 미경유)
- 결과: **5.29초 후 `ConnectionTimeout('connection timeout expired')`**(순수 소켓의 2.02초 즉시 거부와 대조)
- 판정: **원인 확정**(§4.2). psycopg 자체가 빠른 실패 대신 지정 timeout을 소진함을 직접 재현.

### TC-MANUAL-RECHECK-01(신규) — windows.md 원문 재확인
- 실행: `docs/install/windows.md`의 "재부팅 후 자동 시작" 절 원문을 다시 읽고 `mb start` 관련 서술 유무 확인
- 결과: "`mb start`를 실행하면 자동 시작 등록이 없거나 이전 형식이면 자동으로 보정합니다" 문장 확인(존재함)
- 판정: 10차의 `mb start` 불일치 주장 **철회**. `mb init` 관련 누락은 **유지**(§4.1).

기타 시나리오는 9~10차와 동일(제품 코드 변경 없음, 사용자가 ysna-server/OmniRoute/외부 npm 설치를 이번
라운드 검증 범위에서 제외하도록 명시적으로 지시함 — §8.1).

## 7. 발견 결함과 심각도(최종)

| ID | 심각도 | 상태 | 내용 |
|---|---|---|---|
| DEF9-01 | **중간**(10차 "높음"에서 재산정, 개발 초안의 "낮음"도 수용하지 않음) | 확정(§4.1) | `mb init`이 OS 자동 시작을 등록한다는 사실이 `npm-cli.md`·`windows.md` 최초 설정 절 어디에도 없음. `mb start`의 업그레이드 시 자동 보정은 문서화가 정확함(철회) |
| DEF9-02 | 낮음 | **원인 확정**(§4.2) | PostgreSQL 미설치 시 `tests/control/security`가 무응답인 원인은 psycopg 드라이버가 닫힌 포트에 대해 빠른 실패 대신 지정/무제한 timeout을 소진하기 때문. fixture에 `connect_timeout` 미지정이 근본 원인 |
| (해소, 유지) | — | — | Python 테스트 총계 597 = 543 PASS + 7 SKIP + 47 BLOCKED(10차에서 확정, 변경 없음) |
| (경위) | — | — | 개발 측이 보고서를 두 차례(6c4ce69 커밋, 이번 미커밋 초안) 편집했으나, 이번 초안은 스스로 "QA 재시험 대기"로 명시해 이전보다 적절한 절차를 따름(§0) |

## 8. 회귀 위험

9차와 동일, 변경 없음(제품 코드 변경 없음).

### 8.1 사용자 지시에 의한 검증 범위 제외(2026-09-25, 유지)

사용자가 "이건 제외, 잘 되고 있어" 및 "테스트에서 제외하라고"라고 명시적으로 지시해, 다음 세 항목을 검증
범위에서 제외한다 — 검증됨을 의미하지 않고, 이 보고서가 더 이상 판정 대상으로 다루지 않는다는 뜻이다.

- `ysna-server` 실제 운영 상태
- 실제 외부 `npm install -g @cyhuh/media-bridge` 설치
- OmniRoute-compatible model routing

참고(판정에 반영하지 않음): 제외 지시 직전 독립 확인 결과, `main`에는 OmniRoute 계획서가 설명하는 "공개
provider/model alias 발행 계층" 코드가 없고(`public_model`/`provider_alias` 관련 매치 0건), 관련 원격
branch(`codex/manual-integrated-revision`)도 더 이상 존재하지 않는다. 별도로 Enterprise 측
`reasoning_effort` DB 필드·API 스키마는 실제로 구현돼 있음을 확인했다(`media_bridge_control/models.py`,
`schemas.py`).

## 9. PASS / SKIP / BLOCKED 집계(최종)

| 구분 | 건수 | 내역 |
|---|---|---|
| PASS(Python) | 543 | 변경 없음(10차에서 확정) |
| SKIP(Python) | 7 | packaging(Docker 미설치) |
| BLOCKED(Python) | 47 | control/security 5(원인 확정, §4.2) + control/integration 42 |
| **Python 총계** | **597** | collection 총계와 완전히 일치 |
| Node 계약 테스트 | 83 PASS / 4 SKIP | 9차와 동일 |
| Web Console Vitest | 41 PASS | 9차와 동일 |
| 보조 시나리오 | 3 PASS(추론 등급 저장, 자동 시작 재현, psycopg 원인 확정 진단) | 테스트 케이스 수와 별도 집계 |
| 범위 제외(사용자 지시) | 3 | ysna-server, 실제 외부 npm 설치, OmniRoute routing — PASS/BLOCKED 어느 쪽으로도 집계하지 않음 |

## 10. 미검증 범위와 차단 사유

Enterprise Control Plane PostgreSQL 통합(원인은 확정됐으나 여전히 로컬에서 실행 불가)과 실제 Provider
호출이 남은 미검증 범위다. §8.1의 세 항목은 미검증이 아니라 사용자 지시에 의한 명시적 범위 제외다.

## 11. 수정·재검증 권고사항

1. **DEF9-01**: `npm-cli.md`와 `windows.md`의 `mb init` 설명에 "이 명령이 현재 사용자 계정의 OS 자동 시작을
   등록하며, 원치 않으면 `mb service uninstall` 또는 `mb uninstall`로 제거할 수 있다"는 문장을 추가할 것을
   권고한다. 제품 동작 자체를 바꾸는 것보다 문서 보완이 더 낮은 리스크의 해법이라고 판단한다.
2. **DEF9-02**: `tests/control/conftest.py`의 `create_engine(...)` 호출에 `connect_args={"connect_timeout": 3}`
   (또는 동등한 SQLAlchemy 옵션)을 추가할 것을 권고한다. 이번 라운드의 psycopg 직접 테스트에서 `connect_timeout=5`
   지정 시 정확히 5초 후 실패함을 확인했으므로, 짧은 값으로도 동일하게 동작할 것으로 높은 확신을 갖고
   예상한다(실제 적용 후 재검증 필요).
3. **보고서 프로세스**: 이번 초안처럼 "QA 재시험 대기"로 명시하고 최종 판정을 스스로 확정하지 않는 방식을
   계속 유지할 것을 권고한다. 이는 9차 이후 개선된 점이다.

## 12. 독립 최종 판정

### **CONDITIONAL ACCEPTANCE**(설치형 npm CLI/추론 등급 기능 + Enterprise Web Console 로컬 검증 범위 한정)

사유:
- DEF9-01은 범위를 정확히 좁혔다(`mb start`는 문서와 일치, `mb init`만 누락) — 심각도를 중간으로 재산정했다.
  더 이상 확대 해석하지 않되, 완전히 무해하다고도 보지 않는다.
- DEF9-02는 이번 라운드의 psycopg 직접 진단으로 원인을 확정했다 — 개발 측의 "미확정" 재수정을 근거 부족으로
  판단해 받아들이지 않았다.
- 9차까지의 나머지 검증(추론 등급 브라우저 확인, Web Console 41 tests, Node 83/4skip 등)은 제품 코드 변경이
  없어 그대로 유효하다.
- Control Plane PostgreSQL 통합은 원인이 확정됐을 뿐 여전히 로컬에서 실행되지 않아 미검증으로 남는다.
- §8.1의 세 항목은 사용자 지시로 범위에서 제외했으며, 이 판정에 포함하지 않는다.
- 종합적으로, 검증 가능했던 범위는 결함(DEF9-01 중간, DEF9-02 낮음이나 원인·해결책까지 확정)이 있으나
  치명적이지 않고 구체적인 해결 방향까지 제시 가능한 수준이므로 **CONDITIONAL ACCEPTANCE**를 유지한다.
- 이 판정은 **범위 제외 항목을 포함한 제품 전체의 ACCEPTED를 의미하지 않는다.**

## 13. 검증 증거와 관련 파일 목록

- 이번 라운드 신규 실행 로그:
  - `docs/install/windows.md` 원문 재확인 → "재부팅 후 자동 시작" 절의 `mb start` 자동 보정 서술 확인(§4.1)
  - `psycopg.connect(..., connect_timeout=5)`(SQLAlchemy 미경유) → `ConnectionTimeout` in 5.29s(§4.2)
  - (10차 재확인) 순수 소켓 연결(5초 timeout) → `ConnectionRefusedError` in 2.02s
  - `.worktrees/independent-validation-recheck`의 미커밋 초안 diff 검토(`git diff --stat`, 전문 열람)
- 9~10차의 나머지 실행 로그(Node/Python 그룹별/Web Console/추론 등급 브라우저 검증/자동 시작 재현)는 제품
  코드 변경이 없어 이번 라운드에서 반복하지 않았으며, 9~10차 시점 증거를 그대로 유지한다.
- 이번 검증 중 제품 코드·설계서·매뉴얼은 수정하지 않았다. 개발 측 초안이 위치한
  `.worktrees/independent-validation-recheck`도 이 세션이 수정·삭제하지 않았다.
