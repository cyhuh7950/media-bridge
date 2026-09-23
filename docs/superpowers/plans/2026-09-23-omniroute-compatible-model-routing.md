# OmniRoute-compatible model routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make Media Bridge expose published `provider/model` entries while retaining internal analysis-to-LLM routing, and update Test Lab to exercise the same OmniRoute-compatible contract.

**Architecture:** Provider records remain the DB source for credentials and provider defaults. Internal routing remains the N:N execution policy between analysis Providers and Non‑Vision LLM Providers. A separately created public model binds a stable provider alias/model identifier to one internal routing policy; only published public models appear in the signed Gateway snapshot and `/v1/models`.

**Tech Stack:** Python, SQLAlchemy/Alembic, Starlette, signed snapshots, React/TypeScript, pytest, Vitest.

**Spec:** Approved in-chat design on 2026-09-23.

## Global Constraints

- Use only `codex/manual-integrated-revision`; do not create another branch or worktree.
- Provider credentials remain DB-managed and are never exposed in API responses or snapshots.
- Router/Gateway/Aggregator catalog entries such as OmniRoute and OpenRouter are not upstream Provider choices.
- External selection supports omitted model, `auto`, and explicit `provider/model`.
- External reasoning values are `low`, `medium`, and `high`; resolve precedence as request → Provider override → Media Bridge default → system default.
- Existing internal routing N:N behavior and OCR-before-Non‑Vision execution must remain intact.

## Review Focus

- A Provider can be custom and its alias is unique, editable, and safe for public model IDs.
- A public model is not visible in `/v1/models` before publish and disappears after its Provider/routing becomes invalid.
- `auto` chooses through the internal policy/health/capability algorithm rather than a fixed Provider.
- Model omission, `auto`, and explicit `provider/model` remain distinct.
- Test Lab sends the selected public model and standard reasoning value without a routing-profile selector.

### Task 1: Public model and Provider alias contract

**Files:**
- Modify: `media_bridge_control/models.py`, `media_bridge_control/schemas.py`, `media_bridge_control/configuration.py`
- Modify: `media_bridge_control/api.py`, snapshot generation modules
- Create: the next Alembic migration after current head
- Test: Provider/model configuration and migration tests

- [ ] Write failing tests for unique editable Provider aliases, public model creation, publish visibility, and invalid Provider/router references.
- [ ] Add the smallest schema/API fields needed for a Provider alias and a public model binding to an internal routing policy.
- [ ] Implement validation and lifecycle rules without storing credentials in the public model or snapshot.
- [ ] Run focused Python tests and migration checks.
- [ ] Commit the backend contract checkpoint.

### Task 2: Gateway model resolution and reasoning precedence

**Files:**
- Modify: `media_bridge_gateway/runtime.py`, `media_bridge_gateway/app.py`, gateway contracts/transaction modules
- Modify: Provider selection/adapter modules and Media Bridge defaults configuration
- Test: Gateway model listing, omitted/auto/explicit resolution, reasoning precedence, snapshot reload

- [ ] Write failing tests for `/v1/models` generated from published public models and for the three model-selection forms.
- [ ] Implement snapshot public-model projection and keep internal routing resolution separate.
- [ ] Implement `reasoning_effort` precedence and Provider-specific adapter mapping.
- [ ] Run focused gateway tests and compile/lint checks.
- [ ] Commit the Gateway checkpoint.

### Task 3: Console and Test Lab UX

**Files:**
- Modify: `web/src/operations/ProvidersPage.tsx`, `web/src/operations/ModelsPage.tsx`, `web/src/operations/RoutingProfilesPage.tsx`, `web/src/dependencies/TestLabPage.tsx`, `web/src/app/router.tsx`
- Modify: API contracts and related tests/styles
- Test: Operations/Test Lab Vitest and build

- [ ] Write failing UI tests for custom Provider selection, editable alias, public model creation, and omission of router catalogs.
- [ ] Replace Test Lab routing-profile selection with omitted/default, `auto`, and published `provider/model` selection plus `low/medium/high/default` reasoning choice.
- [ ] Keep internal routing management available as the analysis-to-LLM execution policy, without presenting it as the external model identifier.
- [ ] Run Vitest, TypeScript, and production build.
- [ ] Commit the console checkpoint.

### Task 4: Integrated verification and deployment

**Files:**
- Modify: `docs/WORK_STATUS.md` and relevant manual/API documentation

- [ ] Run the complete focused backend/frontend gates and record unverified tests separately.
- [ ] Push the exact branch commit using the configured SSH alias.
- [ ] Deploy the exact commit to WSL-server using the existing `.env`, existing DB, and approved migration procedure.
- [ ] Verify DB head, image digest, health, `/v1/models`, login, and Test Lab browser flow.
- [ ] Report rollback commit/image and remaining acceptance tests; do not merge to main without separate approval.
