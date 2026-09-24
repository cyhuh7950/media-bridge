# Non‑Vision LLM 추론 등급 설정 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 지원되는 Non‑Vision LLM 모델의 추론 등급을 배포형 DB 설정과 설치형 Solar 설정에 저장하고, 미디어 정제 후 실제 LLM 요청에만 정확한 Provider 필드로 반영한다.

**Architecture:** Provider/API/model 조합을 allowlist capability resolver로 판정하고, Control API와 UI는 같은 resolver에서 선택지를 받는다. 배포형은 DB Provider 및 ModelCapability 연결을 서명 snapshot으로 실행에 전달하고 Provider credential은 기존 DB 암호화 경로로만 읽는다. 설치형은 기존 `textLlm` config와 credential 저장소를 유지하며, Gateway와 설치형 downstream은 설정된 effort를 프로토콜별 payload로 변환한다.

**Tech Stack:** Python 3.12, SQLAlchemy/Alembic, Pydantic, Starlette, React 19/TypeScript/Vitest, pytest/httpx.

**Spec:** `docs/superpowers/specs/2026-09-22-llm-reasoning-levels-design.md`

## Global Constraints

- DB Provider와 기존 credential 해석 경로가 배포형 정본이다. Secret 원문은 snapshot, UI, 로그에 넣지 않는다.
- 설치형은 Upstage Solar만 지원하고 사용자 정의 Provider에는 reasoning 설정을 노출하지 않는다.
- 분석 Provider 등록·실행 및 분석 Provider와 Non‑Vision LLM 사이의 N:N 관계는 바꾸지 않는다.
- 기본값은 Provider 기본 동작이며 downstream payload에 reasoning 필드를 넣지 않는다.
- 지원 여부는 Provider ID, protocol, model ID의 검증된 조합으로 판정한다. 호환 API라는 이유만으로 지원을 추정하지 않는다.
- 미지원 조합, 모델 변경 뒤 호환되지 않는 저장값, 모호한 모델→Provider 연결은 fail-closed 한다.
- 제품 변경은 `codex/manual-integrated-revision`에서만 한다. 다른 branch/worktree를 만들지 않고 Git 원격은 SSH alias `github-cyhuh7950`를 사용한다.
- 실제 유료 Provider 호출, 운영 DB migration 적용, ysna-server 배포는 각각 승인 경계를 확인하고 수행한다.
- 각 Task 구현과 해당 Task 검증이 끝나면 그 Task 파일만 커밋하고 동일 허용 branch에 push한 뒤 다음 Task로 진행한다.

## Review Focus

1. 기존 Provider row와 예전 snapshot에 effort가 없음 — `None`을 Provider 기본값으로 취급하고 기존 payload 바이트 의미가 달라지지 않는 회귀 테스트를 둔다.
2. Provider/model/protocol 변경으로 저장 effort가 미지원이 됨 — API validator와 resolver 테스트에서 저장을 거부한다.
3. 같은 model ID에 둘 이상의 Provider가 연결되거나 연결이 없음 — Gateway resolver가 외부 호출 전에 안전한 오류로 중단하는 테스트를 둔다.
4. credential 또는 reasoning trace가 공개 설정/snapshot/log에 섞임 — snapshot/API serialization과 downstream capture에서 secret/trace 미포함을 검증한다.
5. 분석 Provider나 N:N routing 설정이 영향받음 — Provider 수정 전후 분석 유형 및 `analysis_provider_ids`/`llm_provider_ids` 보존 테스트를 둔다.

---

### Task 1: Provider별 추론 capability와 payload mapper

**Files:**
- Create: `media_bridge/reasoning.py`
- Test: `tests/unit/test_reasoning.py`

**Interfaces:**
- `ReasoningEffort`: `Literal["provider_default", "none", "minimal", "low", "medium", "high", "xhigh"]`.
- `ReasoningCapability`: immutable record containing `efforts: tuple[ReasoningEffort, ...]`, `wire_protocol: str`, and `wire_values: tuple[tuple[ReasoningEffort, str | int], ...]` for model-specific remapping.
- `reasoning_capability(catalog_id: str | None, protocol: str | None, model_id: str | None) -> ReasoningCapability | None`.
- `reasoning_payload_fields(capability: ReasoningCapability | None, effort: ReasoningEffort | None) -> dict[str, object]`; default/absent returns `{}`; unsupported value raises `UnsupportedReasoningEffort`.

- [x] **Step 1: Add failing capability and payload tests**

Test OpenAI `gpt-5.1`, `gpt-5-pro`, `o3`, and `o4-mini` on Responses and Chat mappings; Upstage `solar-pro3`/`solar-pro4` Chat `low|medium|high`; Gemini 2.5 `low=1024`, `medium=8192`, `high=24576` budgets and exact active Gemini 3 model-specific level sets (`gemini-3.8-flash`, `gemini-3.6-flash`, `gemini-3.5-flash-lite`, `gemini-3.1-pro-preview`, and `gemini-3.1-flash-lite`); Anthropic adaptive-thinking models `claude-opus-4-6`, `claude-opus-4-7`, `claude-opus-4-8`, `claude-sonnet-4-6`, `claude-opus-5`, `claude-sonnet-5`, and `claude-fable-5` at `low|medium|high`. OpenAI tests must pin GPT-5.1 to `none|low|medium|high`, `gpt-5-pro` to `high`, pre-GPT-5.1 models must reject `none`, and `xhigh` is restricted to model versions documented to support it. Gemini 2.5 `none=0` is allowed only for Flash and Flash-Lite contracts that permit disabling thinking; Gemini 2.5 Pro and Gemini 3 reject it. Non-reasoning models and unverified providers return `None`. Assert default produces no payload fields and invalid level raises.

```python
def test_provider_default_adds_no_reasoning_fields() -> None:
    capability = reasoning_capability("upstage-solar", "openai-chat-completions", "solar-pro4")
    assert capability is not None
    assert reasoning_payload_fields(capability, "provider_default") == {}
```

- [x] **Step 2: Run the focused test and verify it fails**

Run: `uv run pytest tests/unit/test_reasoning.py -q`
Expected: collection or assertions fail because resolver and mapper are not implemented.

- [x] **Step 3: Implement the immutable resolver and mapper**

Implement explicit catalog/protocol/model-family matching. Emit only these verified forms: OpenAI Responses `{"reasoning":{"effort":"high"}}` with the selected canonical value; OpenAI-compatible Chat/Upstage `{"reasoning_effort":"high"}`; Gemini GenerateContent `{"generationConfig":{"thinkingConfig":{"thinkingLevel":"high"}}}` for Gemini 3 and the documented integer `thinkingBudget` mapping for Gemini 2.5; Anthropic Messages `{"thinking":{"type":"adaptive"},"output_config":{"effort":"high"}}` for eligible models. Implement the canonical-to-provider conversion as an explicit table, not guessed ordinal conversion:

```python
def reasoning_payload_fields(capability: ReasoningCapability, effort: ReasoningEffort) -> dict[str, object]:
    if effort == "provider_default":
        return {}
    if effort not in capability.efforts:
        raise UnsupportedReasoningEffort
    wire_value = dict(capability.wire_values)[effort]
    if capability.wire_protocol == "gemini-level":
        return {"generationConfig": {"thinkingConfig": {"thinkingLevel": wire_value}}}
    if capability.wire_protocol == "gemini-budget":
        return {"generationConfig": {"thinkingConfig": {"thinkingBudget": wire_value}}}
    if capability.wire_protocol == "openai-responses":
        return {"reasoning": {"effort": wire_value}}
    if capability.wire_protocol == "openai-chat":
        return {"reasoning_effort": wire_value}
    return {"thinking": {"type": "adaptive"}, "output_config": {"effort": wire_value}}
```

The mapper accepts no request payload; it returns a fresh field mapping on each call, which the adapter merges into its own request body. Other catalog/custom providers remain default-only until their exact API/model contract is verified.

- [x] **Step 4: Run focused tests and lint**

Run: `uv run pytest tests/unit/test_reasoning.py -q` and `uv run ruff check media_bridge/reasoning.py tests/unit/test_reasoning.py`
Expected: all mapping, default omission, unsupported model, and independently constructed result-mapping tests pass.

### Task 2: DB persistence, Control API validation, and signed snapshot

**Approval gate:** Before implementing this task, obtain explicit approval to add nullable `providers.reasoning_effort` and migration `0009_provider_reasoning_effort`. Before deployment, obtain approval to apply that migration to ysna-server’s persistent database.

**Files:**
- Modify: `media_bridge_control/models.py:Provider`
- Modify: `media_bridge_control/schemas.py:ProviderCreate`, `ProviderUpdate`
- Modify: `media_bridge_control/configuration.py:_provider_values`, `_provider`, `_snapshot_body`
- Modify: `media_bridge_control/api.py:provider_item` and add `GET /admin/v1/provider-reasoning-options`
- Modify: `media_bridge/snapshots.py` only as required to validate the additional non-secret snapshot fields
- Create: `migrations/versions/0009_provider_reasoning_effort.py`
- Test: `tests/control/unit/test_managed_provider_schema.py`
- Test: `tests/control/integration/test_migrations.py`, `tests/control/integration/test_snapshot_admin_api.py`, `tests/control/integration/test_configuration_api.py`

**Interfaces:**
- Persist `Provider.reasoning_effort` as nullable `String(16)`; SQL `NULL` means provider default and does not rewrite old rows. API reads serialize SQL `NULL` as `provider_default`; create/update input `provider_default` normalizes to SQL `NULL`.
- Provider create/update accept the seven canonical values; only `kind="llm"` and a supported resolver result may store a non-default value.
- Add authenticated `GET /admin/v1/provider-reasoning-options` with `catalog_id`, `protocol`, and `model_id` query parameters; for example `?catalog_id=upstage-solar&protocol=openai-chat-completions&model_id=solar-pro4`. Return a concrete `efforts` string array without credential data.
- Snapshot provider records carry `reasoning_effort`; snapshot model entries preserve `provider_id` and aliases required to resolve the requested public model to one Provider.

- [ ] **Step 1: Add failing schema, migration, serialization, and options-endpoint tests**

Test nullable legacy rows, supported LLM values, rejection for analysis/unsupported models, model update invalidation, authenticated options lookup, and snapshot inclusion without `encrypted_api_key`. Test Alembic upgrade/downgrade round-trip with the existing migration fixtures.

```python
def test_provider_snapshot_keeps_default_and_never_exposes_key(provider, configuration):
    snapshot_provider = next(item for item in configuration.snapshot_body()["providers"] if item["id"] == str(provider.id))
    assert snapshot_provider["reasoning_effort"] is None
    assert "encrypted_api_key" not in snapshot_provider
```

- [ ] **Step 2: Run focused tests to verify failure**

Run: `uv run pytest tests/control/unit/test_managed_provider_schema.py tests/control/integration/test_migrations.py tests/control/integration/test_snapshot_admin_api.py -q`
Expected: failures identify the missing nullable column, schema field, options response, and snapshot data.

- [ ] **Step 3: Implement migration and DB/API/snapshot mapping**

Create `0009_provider_reasoning_effort` after `0008_model_provider`; upgrade adds a nullable column and changes no existing row values; downgrade drops only that new column. Validate effort against `reasoning_capability` after combining ProviderCreate with existing values on PATCH. Reject incompatible model/protocol edits rather than silently resetting a saved effort. Include Provider ID on snapshot model records while retaining existing snapshot fields and signatures.

```python
op.add_column("providers", sa.Column("reasoning_effort", sa.String(length=16), nullable=True))
```

- [ ] **Step 4: Run Control and migration tests**

Run: `uv run pytest tests/control/unit/test_managed_provider_schema.py tests/control/integration/test_migrations.py tests/control/integration/test_snapshot_admin_api.py tests/control/integration/test_configuration_api.py -q`
Expected: DB persistence, API rejection rules, old snapshot compatibility, and secret omission pass. If PostgreSQL fixture cannot run in Windows, record it as unverified and use the established PostgreSQL integration environment; do not mark it passed.

### Task 3: Provider registration/edit reasoning selector

**Files:**
- Modify: `web/src/operations/ProvidersPage.tsx`
- Modify: `web/src/api/contracts.ts` to add the optional `reasoning_effort` Provider response/request field
- Test: `web/src/operations/Operations.test.tsx`

**Interfaces:**
- The form stores `reasoning_effort` for `kind="llm"`; it queries the options endpoint using current catalog ID, protocol, and model ID.
- Analysis Provider forms never render the selector; changing Provider/model/protocol refreshes available choices. If a persisted selection becomes incompatible, show the stale selection as unsupported and require an explicit valid choice before submit.

- [ ] **Step 1: Add failing create/edit UI tests**

Assert an eligible OpenAI/Upstage/Gemini/Anthropic model shows only returned levels; unsupported models show Provider default only; selecting analysis hides the LLM selector; changing an eligible model to unsupported does not submit the stale level; create, edit, and reload retain the selected effort.

```tsx
expect(screen.getByLabelText("추론 등급")).toHaveValue("provider_default");
await user.selectOptions(screen.getByLabelText("추론 등급"), "high");
expect(submittedProvider.reasoning_effort).toBe("high");
```

- [ ] **Step 2: Run the focused Web test and verify failure**

Run from `web`: `npm test -- --run src/operations/Operations.test.tsx`
Expected: new selector assertions fail because the form currently has no reasoning field.

- [ ] **Step 3: Implement options loading and safe form submission**

Use the existing `adminRequest` and CSRF-protected provider POST/PATCH. Add an accessible Korean `추론 등급` label and `Provider 기본값`; serialize exactly `reasoning_effort`. Refresh options when catalog ID, protocol, or model changes. Keep analysis Provider type, catalog picker, model input, and routing profile arrays unchanged.

```tsx
const body = {
  name, kind, catalog_id: catalogId || undefined, model_id: modelId || undefined,
  endpoint, protocol: protocol || undefined, capabilities,
  reasoning_effort: kind === "llm" ? reasoningEffort : undefined,
};
```

- [ ] **Step 4: Run focused UI, lint, and type checks**

Run from `web`: `npm test -- --run src/operations/Operations.test.tsx`, `npm run lint`, `npm run typecheck`
Expected: tests, lint, and typecheck pass.

### Task 4: DB-selected Gateway LLM execution

**Files:**
- Create: `media_bridge/llm_backends.py`
- Modify: `media_bridge/backends.py` only to reuse/extend the existing `AnalysisBackend` contract without changing OCR/Vision behavior
- Modify: `media_bridge_gateway/downstream.py:ProviderResponsesDownstream`
- Modify: `media_bridge_gateway/entrypoints.py` provider loading, credential callback, and snapshot downstream factory
- Modify: `media_bridge_control/configuration.py:_snapshot_body` if model/provider mapping needs additional serialization
- Test: `tests/unit/test_backends.py`
- Test: `tests/gateway/unit/test_entrypoint.py`
- Test: `tests/gateway/integration/test_responses_transaction.py`
- Test: `tests/gateway/integration/test_snapshot_generation.py`

**Interfaces:**
- `build_llm_backend(provider: Mapping[str, object], *, credential_loader: Callable[[], str], client: httpx.AsyncClient) -> AnalysisBackend` selects an adapter only for the protocol allowlist.
- `ProviderResponsesDownstream` resolves `SealedGatewayRequest.target_id` through the verified snapshot’s unique model→provider mapping, then uses that provider’s endpoint, model, protocol, and saved effort. Existing N:N analysis/LLM routing-profile membership is not changed by this feature.
- `entrypoints` resolves API credentials by Provider UUID from encrypted DB data at call time; no credential enters snapshot or backend diagnostics.

- [ ] **Step 1: Add failing adapter and runtime resolution tests**

Use `httpx.MockTransport` to assert exact request JSON and response parsing for Chat Completions and Responses. Chat uses `messages`; Responses uses text-only `input`. Test media has already been converted to text before provider call; target-model ambiguity, missing Provider, unsupported protocol, client-supplied reasoning override, and invalid effort cause zero HTTP calls; default payloads contain no reasoning fields; analysis Provider and N:N records are unchanged.

```python
matches = provider_resolver.providers_for_model(request.target_id, snapshot)
if len(matches) != 1:
    raise DownstreamError("model_provider_unavailable", "No unique Provider is configured.")
```

- [ ] **Step 2: Run focused tests to verify failure**

Run: `uv run pytest tests/unit/test_backends.py tests/gateway/unit/test_entrypoint.py tests/gateway/integration/test_responses_transaction.py tests/gateway/integration/test_snapshot_generation.py -q`
Expected: current fixed Solar backend fails the new non-Solar dispatch and reasoning payload assertions.

- [ ] **Step 3: Implement provider adapter construction and target-model dispatch**

Build the Chat Completions and Responses adapters from signed snapshot metadata at generation creation. Resolve target model using the model capability’s Provider ID; if no unique eligible mapping exists, return a bounded `model_provider_unavailable` error before opening a socket. Read current credential through the existing DB decryption callback. Feed only sanitized text from `ProviderResponsesDownstream` into the selected adapter. Do not alter OCR/Vision backends or routing-profile membership.

```python
backend = build_llm_backend(provider, credential_loader=credential_loader, client=client)
result = await backend.analyze(context=prompt, user_request="")
```

- [ ] **Step 4: Run Gateway/runtime tests**

Run: `uv run pytest tests/unit/test_backends.py tests/gateway/unit/test_entrypoint.py tests/gateway/integration/test_responses_transaction.py tests/gateway/integration/test_snapshot_generation.py tests/control/integration/test_gateway_snapshot_credentials.py -q`
Expected: Chat/Responses payloads, provider selection, default compatibility, DB credential use, and secret-free snapshot tests pass.

### Task 5: Native Gemini and Anthropic downstream adapters

**Files:**
- Modify: `media_bridge/llm_backends.py`
- Test: `tests/unit/test_backends.py`
- Test: `tests/gateway/integration/test_responses_transaction.py`

**Interfaces:**
- Extend `build_llm_backend(...)` with `gemini-generate-content` and `anthropic-messages` while retaining the Task 4 Chat/Responses signatures.
- Gemini uses the configured `model_id` to build `https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent`, sends API key in `x-goog-api-key`, and parses `candidates[0].content.parts[].text`.
- Anthropic posts to `/v1/messages`, sends `x-api-key` plus fixed `anthropic-version`, and parses text blocks only.

- [ ] **Step 1: Add failing Gemini and Anthropic adapter tests**

Use `httpx.MockTransport` to assert exact endpoint, headers, request bodies, response parsing, and canonical effort mappings. Test default omission, unsupported-model rejection, invalid credential response, and safe handling of upstream 4xx without retries or response-body disclosure.

```python
assert request.headers["x-api-key"] == "test-key"
assert request.json()["output_config"]["effort"] == "high"
```

- [ ] **Step 2: Run the focused adapter tests and verify failure**

Run: `uv run pytest tests/unit/test_backends.py tests/gateway/integration/test_responses_transaction.py -q`
Expected: tests fail because the native protocols are not in the adapter registry.

- [ ] **Step 3: Implement native request/response adapters**

Build Gemini GenerateContent request with `contents=[{"role":"user","parts":[{"text":prompt}]}]`; put mapped `thinkingLevel` or `thinkingBudget` under `generationConfig.thinkingConfig`. Build Anthropic request with `model`, `max_tokens`, `messages`, optional adaptive `thinking`, and `output_config.effort`. Keep response parsing constrained to visible text blocks; never return or log internal thought fields.

```python
body = {"model": model, "contents": [{"role": "user", "parts": [{"text": prompt}]}]}
body.update(reasoning_payload_fields(capability, effort))
```

- [ ] **Step 4: Run native adapter tests and lint**

Run: `uv run pytest tests/unit/test_backends.py tests/gateway/integration/test_responses_transaction.py -q` and `uv run ruff check media_bridge/llm_backends.py tests/unit/test_backends.py`
Expected: Gemini/Anthropic adapter contracts and safe error tests pass.

### Task 6: Installed Solar settings and downstream payload

**Files:**
- Modify: `media_bridge_personal/npm_runtime.py:_validated_generic_settings`, `_public_settings`, `_settings_page`, `_settings_script`, `ProviderTester`, `build_personal_runtime`, and the settings API route table
- Modify: `media_bridge_personal/solar_responses.py:SolarResponsesDownstream`
- Test: `tests/personal/test_npm_runtime.py`
- Test: `tests/personal/test_solar_responses.py`
- Test: `tests/personal/test_runtime.py`

**Interfaces:**
- Persist `textLlm.reasoningEffort` in existing `config.json`; absent value normalizes to `provider_default`.
- `GET /api/reasoning-options?preset=upstage-solar&protocol=openai-chat-completions&model=solar-pro4` returns a concrete `efforts` string array from the shared resolver; the handler accepts the same three named query parameters for other Solar model/protocol values.
- `SolarResponsesDownstream(..., reasoning_effort: ReasoningEffort = "provider_default")` applies only the verified Solar Chat Completions field; it must reject unsupported Solar model/protocol/effort combinations.

- [ ] **Step 1: Add failing settings and downstream tests**

Test HTML selector appears only for eligible Solar model/protocol; custom preset remains excluded; old config loads as provider default; POST saves/reloads selected effort; text LLM test and whole-pipeline test send the same setting; Chat payload has `reasoning_effort` only when selected; default has no such field; Responses protocol never receives a Chat-only parameter.

```python
saved = _validated_generic_settings(valid_payload | {"textLlm": {"reasoningEffort": "high"}}, current)
assert saved["textLlm"]["reasoningEffort"] == "high"
```

- [ ] **Step 2: Run focused Personal tests and verify failure**

Run: `uv run pytest tests/personal/test_npm_runtime.py tests/personal/test_solar_responses.py tests/personal/test_runtime.py -q`
Expected: tests fail because the UI, validator, settings payload, and downstream do not currently carry effort.

- [ ] **Step 3: Implement Solar-only settings persistence and request mapping**

Use the existing secret store unchanged. Include `reasoningEffort` in page render, browser payload, config validator, public settings, runtime construction, connection test, and whole-pipeline test. Implement the local same-origin options route with the shared resolver so model changes refresh choices without duplicating the capability matrix. If the current selection becomes unsupported, require an explicit compatible choice or Provider default before save. Do not accept arbitrary per-request reasoning fields.

```javascript
textLlm: {
  preset: field('text_llm_preset').value,
  model: field('solar_model').value,
  reasoningEffort: field('reasoning_effort').value,
}
```

- [ ] **Step 4: Run Personal tests and packaging checks**

Run: `uv run pytest tests/personal/test_npm_runtime.py tests/personal/test_solar_responses.py tests/personal/test_runtime.py tests/packaging/test_personal_package_launchers.py -q`
Expected: old config compatibility, persistence, actual mock payload, and package launcher tests pass.

### Task 7: End-to-end contract, operator manual, and full verification

**Files:**
- Modify: `docs/manuals/MEDIA_BRIDGE_OPERATIONS_MANUAL.md`
- Modify: `docs/manuals/Media-Bridge-Integrated-Manual.docx` using the `documents` skill and its render-and-verify workflow
- Modify: `docs/WORK_STATUS.md`
- Test: relevant `tests/control`, `tests/gateway`, `tests/personal`, and `web` suites

**Interfaces:**
- Manual documents must explain deployment Provider/model support and default, installed Solar selection, how the setting affects requests, unsupported-model behavior, and the fact that analysis Provider/N:N wiring is unchanged.
- Work status records commits, exact test commands/results, migration approval/application state, external calls, deployment commit/image/health, and remaining acceptance evidence.

- [ ] **Step 1: Add full-path fixture tests**

Test DB Provider effort → signed snapshot → selected model/provider → sanitized text → protocol-specific request body; test installation settings save → runtime reconstruction → Solar request body. Assert OCR/analysis selection and routing profile ID arrays before/after remain identical.

```python
assert downstream_request.json()["reasoning_effort"] == "high"
assert "encrypted_api_key" not in snapshot_provider
```

- [ ] **Step 2: Run complete automated gates**

Run: `uv run pytest`; `uv run ruff check .`; `uv run mypy`; from `web`, `npm test -- --run`, `npm run lint`, `npm run typecheck`, `npm run build`.
Expected: all required gates pass. PostgreSQL-specific tests must run against PostgreSQL; skipped fixtures are explicitly reported as unverified.

- [ ] **Step 3: Update and visually verify the integrated Word manual**

Use the `documents` skill, render the edited DOCX, inspect every changed page, and correct layout before marking documentation complete.

- [ ] **Step 4: Run mock-based end-to-end regression**

Run the Gateway and Personal E2E subsets with mock Provider transports. Verify supported settings reach each intended adapter, unsupported models fail closed, and default behavior omits all reasoning parameters.

- [ ] **Step 5: Commit the verified task set and push the allowed branch**

Stage only this feature’s implementation, tests, manuals, and `docs/WORK_STATUS.md`; commit on `codex/manual-integrated-revision`; push through SSH alias `github-cyhuh7950`; verify local HEAD equals the upstream ref and the worktree is clean.

- [ ] **Step 6: Acceptance deployment and handoff**

After all gates pass and migration application is explicitly approved, deploy the exact pushed commit to ysna-server using the project’s deployment procedure. Record image digest, container health, migration version, and smoke results; provide `https://media-bridge.sinsan.kr/` and rollback reference for user acceptance. Do not merge to `main` or create/delete branches as part of this plan.

## Official API references used for the initial capability matrix

- OpenAI reasoning models and effort values: https://platform.openai.com/docs/api-reference/responses
- Gemini model-specific `thinkingLevel`/`thinkingBudget`: https://ai.google.dev/gemini-api/docs/thinking
- Anthropic adaptive thinking and effort: https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/prompt-templates-and-variables
- Upstage Solar reasoning example: https://console.upstage.ai/api-keys?api=chat-reasoning
- Upstage Solar Pro 4 effort behavior: https://www.upstage.ai/blog/ko/solar-pro-4
- Gemini GenerateContent model-specific thinking controls and active model IDs: https://ai.google.dev/gemini-api/docs/generate-content/thinking and https://ai.google.dev/gemini-api/docs/models
