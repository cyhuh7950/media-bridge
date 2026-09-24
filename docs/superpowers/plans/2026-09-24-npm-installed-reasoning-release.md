# npm Installed Reasoning Release Candidate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and validate an unpublished `@cyhuh/media-bridge@0.1.14` installation candidate that contains the installed reasoning-level settings on Windows x64, Linux x64, and Linux ARM64.

**Architecture:** Reuse the three native runtime workflows with version and source-revision inputs, then orchestrate them from the approved feature branch. Assemble a candidate-only runtime manifest and npm tarball from matching artifacts, and install/test the tarball in isolated runner environments without creating a public release or publishing to npm.

**Tech Stack:** GitHub Actions YAML, Node.js 22/24, npm, Python 3.13, existing runtime builder/verifier scripts, Node `node:test`, npm tarballs.

**Spec:** `docs/superpowers/specs/2026-09-24-npm-installed-reasoning-release-design.md`

## Global Constraints

- Candidate version is `0.1.14`.
- All three runtime artifacts must use the same source commit and candidate version.
- The candidate package and manifest are GitHub Actions workflow artifacts, not formal Release assets or npm publication; their access follows repository visibility and GitHub permissions, and no Secret may be included.
- Candidate manifest URLs use the future release asset path; candidate verification overrides downloads to loopback.
- No public release, tag, asset upload, npm publish, `main` merge, ysna/server deployment, or modification of the user's `127.0.0.1:8642` installation.
- Do not use a personal GitHub login, PAT, or alternate account; Git operations use the configured `github-cyhuh7950` alias.
- Tests use a separate HOME, npm prefix, synthetic secret, temporary ports, and temporary runtime/config paths.

## Review Focus

- A platform artifact from a different commit or version must be rejected before packaging; test mixed evidence and mismatching hashes.
- A candidate trigger must not grant write permissions or run from unrelated branches/tags; test trigger filters and least-privilege permissions.
- The future public asset URL must not be fetched during candidate tests; test explicit loopback URL override and verify the configured endpoint remains untouched.
- Installing the tarball must select the correct native runtime and expose the new settings UI/API; test on each native runner rather than relying on `npm pack` alone.
- Release tag dispatch and manual candidate execution must not accidentally create a GitHub release or publish to npm; test the `release-v<packageVersion>` condition and publish job dependencies.

---

### Task 1: Pin candidate workflow contracts with failing tests

**Files:**
- Modify: `tests/npm/media-bridge-linux-runtime-release.test.cjs`
- Modify: `tests/npm/media-bridge-release-0111.test.cjs` (rename only if the test suite already supports a version-neutral name without weakening historical assertions)
- Create: `tests/npm/media-bridge-release-candidate.test.cjs`
- Inspect: `.github/workflows/build-runtime-linux-x64.yml`, `.github/workflows/build-runtime-linux-arm64.yml`, `.github/workflows/build-runtime-win32-x64.yml`, `.github/workflows/publish-npm-runtime-release.yml`

**Interfaces:**
- Consumes: Existing runtime builder inputs `version`, `output-dir`, `work-dir`, `base-url`; existing verifier output `verification-result.json` with source commit, SHA-256, and health status.
- Produces: Test contracts for reusable build workflow inputs, candidate trigger scope, artifact identity checks, candidate-only packaging, and tag-gated publish behavior.

- [x] **Step 1: Write failing tests** asserting each native build workflow accepts a validated version and checks out the requested source SHA; candidate orchestration builds all three platforms at `0.1.14`; artifact assembly rejects any mismatch in version, commit, checksum, or verifier health; candidate workflow contains no release-creation or npm-publish step; publish remains guarded by an exact release tag.
- [x] **Step 2: Run the focused Node tests** with `node --test tests/npm/media-bridge-release-candidate.test.cjs tests/npm/media-bridge-linux-runtime-release.test.cjs`; confirm failures identify absent candidate contracts, not YAML parser or environment setup errors.
- [x] **Step 3: Keep historical release tests intact** by changing only assumptions that incorrectly require the live current version to remain permanently `0.1.13`; preserve assertions for old published release metadata where it is historical evidence.
- [x] **Step 4: Re-run the focused Node tests** and confirm the tests fail only on the intended missing candidate workflow behavior.

### Task 2: Make platform runtime builders reusable and revision-specific

**Files:**
- Modify: `.github/workflows/build-runtime-linux-x64.yml`
- Modify: `.github/workflows/build-runtime-linux-arm64.yml`
- Modify: `.github/workflows/build-runtime-win32-x64.yml`
- Modify: `packaging/runtime/verify-linux-x64.sh`
- Modify: `packaging/runtime/verify-linux-arm64.sh`
- Modify: `packaging/runtime/verify-win32-x64.ps1`
- Test: `tests/npm/media-bridge-release-candidate.test.cjs`

**Interfaces:**
- Consumes: Validated inputs `version` and `source_commit`; existing tag-trigger behavior for public runtime builds.
- Produces: `workflow_call`-compatible builders that check out one exact source commit, produce versioned native artifacts, and attach verifiable source/version evidence.

- [x] **Step 1: Add reusable workflow inputs** for semantic runtime version and source commit while retaining existing `runtime-v*` and manual dispatch entry points.
- [x] **Step 2: Validate inputs before checkout/build** using `^[0-9]+\.[0-9]+\.[0-9]+$` for version and a full 40-character hexadecimal SHA for source commit; reject missing or malformed values.
- [x] **Step 3: Check out the exact requested source commit** for candidate calls and preserve tag-derived source selection for existing public runtime builds.
- [x] **Step 4: Ensure each verifier evidence file names the same source SHA, artifact version, platform, SHA-256, and health status; fail the job if any field is absent or inconsistent.
- [x] **Step 5: Run the workflow contract tests** and the existing Linux/Windows runtime artifact contract tests to confirm the historic tag build path still works.

### Task 3: Orchestrate the candidate build and native install matrix

**Files:**
- Create: `.github/workflows/build-npm-runtime-candidate.yml`
- Create: `packaging/npm/scripts/assemble-candidate.cjs`
- Create: `packaging/npm/scripts/verify-candidate-install.cjs`
- Modify: `tests/npm/media-bridge-release-candidate.test.cjs`
- Modify: `packaging/npm/package.json` only if a narrowly scoped npm script is needed to run candidate verification; do not change published version yet.

**Interfaces:**
- Consumes: Three platform build workflow artifacts, all keyed to the candidate source SHA and `0.1.14`.
- Produces: Candidate assembly script taking artifact directories, source SHA, and version; candidate manifest with actual artifact checksums and future public URLs; native runner install verification result.

- [x] **Step 1: Add failing assembler tests** for valid evidence, missing platform, incorrect artifact filename, mismatched source SHA, mismatched version, SHA mismatch, and non-200 health evidence.
- [x] **Step 2: Implement the minimal assembler** to copy the three archives and verification records, derive SHA-256 from bytes, and generate a temporary candidate manifest without editing tracked release metadata.
- [x] **Step 3: Add failing install checks** for manifest runtime selection, future URL override to loopback, isolated npm prefix/HOME, version output, health, reasoning selectors, settings API persistence, and explicit Non-Vision LLM override precedence.
- [x] **Step 4: Implement native candidate install verification** using only runner temporary paths and synthetic settings; assert that no request targets the future public URL and do not contact Upstage.
- [x] **Step 5: Add the candidate workflow** with `contents: read` and `actions: read` only, restricted to pushes on `codex/installed-reasoning-level-config` that change installed runtime/npm packaging/workflow files. It must call all three native builders at the same `github.sha` and `0.1.14`.
- [x] **Step 6: Assemble and retain candidate evidence** (manifest, archives, verifier JSON, npm tarball, install results) as Actions workflow artifacts with bounded retention; access follows repository visibility. Do not include secrets or grant `contents: write` or `id-token: write`.
- [x] **Step 7: Run the candidate workflow contract and assembly tests locally** and confirm candidate mode cannot create tags, releases, public assets, or registry publications.

### Task 4: Remove hard-coded release-version coupling without enabling publication

**Files:**
- Modify: `.github/workflows/publish-npm-runtime-release.yml`
- Modify: `tests/npm/media-bridge-release-candidate.test.cjs`
- Inspect: `packaging/npm/package.json`, `packaging/npm/runtime-manifest.json`

**Interfaces:**
- Consumes: Exact release tag, package version, release metadata commit, and three verified runtime artifact identities.
- Produces: A version-generic public workflow whose release path is driven by the exact `release-v<version>` tag and evidence inputs, with no candidate workflow dependency on publication credentials.

- [x] **Step 1: Add failing tests** for version/tag mismatch, source SHA mismatch, artifact identity mismatch, manual dispatch safety, and the requirement that `npm publish` is reachable only for an exact release tag after release asset validation.
- [x] **Step 2: Replace hard-coded `0.1.13`, source SHA, and Actions run IDs** with validated workflow/tag inputs and artifact names tied to the verified source SHA; retain the existing release metadata wording for historical release records only.
- [x] **Step 3: Preserve the exact tag gate** on the npm publishing job and narrow permissions so candidate workflows cannot inherit release write or npm OIDC permissions.
- [x] **Step 4: Run release contract tests** for both candidate/manual paths and exact tag paths; do not dispatch a release workflow, create a tag, or publish.

### Task 5: Prepare version `0.1.14` candidate metadata and verify packed package

**Files:**
- Modify: `packaging/npm/package.json`
- Inspect only: `packaging/npm/runtime-manifest.json`; candidate values are generated into a temporary staging copy, never written to this tracked release manifest.
- Modify: `tests/npm/media-bridge-runtime.test.cjs`
- Modify: `tests/npm/media-bridge-docs.test.cjs`
- Modify: `docs/WORK_STATUS.md`

**Interfaces:**
- Consumes: Candidate artifact evidence generated from one exact source commit on all native platforms.
- Produces: Version `0.1.14` npm package metadata and a locally packable candidate whose runtime URLs/checksums are injected from verified workflow artifacts only during candidate assembly.

- [x] **Step 1: Update version contract tests** to use an explicit candidate version input rather than freezing every future release to `0.1.13`; retain historical `0.1.13` metadata expectations only in tests that explicitly validate that published release.
- [x] **Step 2: Change npm package version to `0.1.14`** and make candidate assembly generate its runtime manifest in a temporary package staging directory; do not mark unpublished placeholder hashes as published in tracked source or modify the tracked `runtime-manifest.json`.
- [x] **Step 3: Run `npm pack --dry-run` and `npm pack`** in `packaging/npm` with isolated npm cache/temp output; inspect the exact tarball file list to ensure it contains CLI, manifest, library, docs, and no tests, secrets, caches, or build intermediates.
- [ ] **Step 4: Install the resulting tarball into an isolated local prefix** where a native runtime artifact is available, then run CLI health/settings UI/API assertions without touching the existing 8642 installation.
- [ ] **Step 5: Update `docs/WORK_STATUS.md`** with source SHA, candidate version, per-platform artifact evidence, actual npm tarball/install results, failures, and all remaining unverified/publication boundaries.

### Task 6: Run the full approved verification gate and checkpoint

**Files:**
- Verify: `tests/npm/`
- Verify: `tests/packaging/test_runtime_artifact_contract.py`
- Verify: `.github/workflows/build-npm-runtime-candidate.yml`
- Verify: `.github/workflows/build-runtime-linux-x64.yml`, `.github/workflows/build-runtime-linux-arm64.yml`, `.github/workflows/build-runtime-win32-x64.yml`, `.github/workflows/publish-npm-runtime-release.yml`
- Modify: `docs/WORK_STATUS.md`

**Interfaces:**
- Consumes: Completed implementation and candidate workflow evidence.
- Produces: An auditable verification report tied to the exact source SHA and a clean, pushed feature branch; no public release or server deployment.

- [x] **Step 1: Run the complete npm test suite** with `node --test tests/npm/*.test.cjs`; record actual pass/fail/skip totals.
- [ ] **Step 2: Run Python packaging tests** with the repository's supported environment and the project's configured pytest command; record platform-specific skips/failures rather than masking them.
- [x] **Step 3: Run package lint/type/build checks** only where configured for the npm runtime; inspect `package.json` scripts and execute the exact repository commands.
- [x] **Step 4: Run `git diff --check`, inspect all workflow permissions/triggers and package contents, and verify the branch contains no secret, temporary file, release tag, or public publication side effect.
- [x] **Step 5: Commit and push each completed checkpoint** using `github-cyhuh7950`; verify local branch HEAD equals `origin/codex/installed-reasoning-level-config` and leave unrelated branches/worktrees untouched.
- [x] **Step 6: Report candidate evidence and limitations**. If GitHub Actions native runners are unavailable, state that the three-platform candidate is not complete; do not call the local `npm pack` result a successful multi-platform npm install.
