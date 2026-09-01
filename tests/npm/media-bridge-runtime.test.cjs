const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const {
  platformKey,
  resolveRuntime,
  runtimeDir,
} = require('../../packaging/npm/lib/runtime.cjs');

test('runtime platform key supports the release target matrix', () => {
  assert.equal(platformKey('linux', 'x64'), 'linux-x64');
  assert.equal(platformKey('linux', 'arm64'), 'linux-arm64');
  assert.equal(platformKey('win32', 'x64'), 'win32-x64');
  assert.throws(() => platformKey('freebsd', 'x64'), /unsupported/i);
});

test('runtime resolver honors an explicit local runtime command for QA', async () => {
  const result = await resolveRuntime({
    homeDir: path.join(__dirname, '../../.tmp-runtime-override'),
    env: { MEDIA_BRIDGE_RUNTIME_COMMAND: process.execPath },
    platform: 'win32',
    arch: 'x64',
  });
  assert.equal(result.command, process.execPath);
  assert.deepEqual(result.args, []);
});

test('runtime resolver fails closed when no managed artifact is available', async () => {
  const tempHome = path.join(__dirname, '../../.tmp-runtime-missing');
  fs.rmSync(tempHome, { recursive: true, force: true });
  await assert.rejects(() => resolveRuntime({
    homeDir: tempHome,
    env: {},
    platform: 'linux',
    arch: 'x64',
  }), /runtime.*(available|artifact)|artifact.*(available|configured)/i);
  assert.equal(fs.existsSync(runtimeDir(tempHome)), false);
});
