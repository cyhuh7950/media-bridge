const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const root = path.resolve(__dirname, '../..');
const workflowRoot = path.join(root, '.github', 'workflows');

test('each native runtime builder accepts a version and exact source commit through workflow_call', () => {
  for (const name of [
    'build-runtime-linux-x64.yml',
    'build-runtime-linux-arm64.yml',
    'build-runtime-win32-x64.yml',
  ]) {
    const workflow = fs.readFileSync(path.join(workflowRoot, name), 'utf8');
    assert.match(workflow, /workflow_call:/, `${name} must be reusable`);
    assert.match(workflow, /source_commit:/, `${name} must accept source_commit`);
    assert.match(workflow, /version:/, `${name} must accept version`);
    assert.match(workflow, /ref:\s*\$\{\{\s*inputs\.source_commit\s*\|\|\s*github\.sha\s*\}\}/,
      `${name} must check out the requested source commit`);
  }
});

test('each native verifier records the runtime version in its evidence', () => {
  for (const name of [
    'verify-linux-x64.sh',
    'verify-linux-arm64.sh',
    'verify-win32-x64.ps1',
  ]) {
    const verifier = fs.readFileSync(path.join(root, 'packaging', 'runtime', name), 'utf8');
    assert.match(verifier, /runtimeVersion/, `${name} must record the verified runtime version`);
  }
});

test('candidate workflow is limited to the approved branch and read-only permissions', () => {
  const file = path.join(workflowRoot, 'build-npm-runtime-candidate.yml');
  assert.ok(fs.existsSync(file), 'candidate orchestration workflow must exist');
  const workflow = fs.readFileSync(file, 'utf8');
  assert.match(workflow, /codex\/installed-reasoning-level-config/);
  assert.match(workflow, /contents:\s*read/);
  assert.match(workflow, /actions:\s*read/);
  assert.doesNotMatch(workflow, /contents:\s*write|id-token:\s*write|npm publish|createRelease/);
  for (const platform of ['linux-x64', 'linux-arm64', 'win32-x64']) {
    assert.ok(workflow.includes(platform), `candidate must build ${platform}`);
  }
  assert.match(workflow, /github\.sha/);
  assert.match(workflow, /0\.1\.14/);
});

test('public release workflow is version-driven and npm publication requires its exact release tag', () => {
  const workflow = fs.readFileSync(path.join(workflowRoot, 'publish-npm-runtime-release.yml'), 'utf8');
  assert.doesNotMatch(workflow, /VERSION:\s*0\.1\.13|TAG:\s*v0\.1\.13|SOURCE_COMMIT:\s*5e0f295/);
  assert.match(workflow, /release-v\$package_version/);
  assert.match(workflow, /publish-npm-package:[\s\S]*?if:\s*github\.ref_type\s*==\s*'tag'/);
});
