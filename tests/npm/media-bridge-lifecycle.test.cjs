const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const processApi = require('../../packaging/npm/lib/process.cjs');

function home(name) {
  const value = path.join(__dirname, `../../.tmp-npm-lifecycle-${name}`);
  fs.rmSync(value, { recursive: true, force: true });
  fs.mkdirSync(value, { recursive: true });
  return value;
}

test('lifecycle starts a managed child and removes its state on stop', async () => {
  const homeDir = home('start-stop');
  const runtime = {
    command: process.execPath,
    args: ['-e', 'setInterval(() => {}, 1000)'],
    env: process.env,
    python: false,
  };
  const state = await processApi.startProcess({
    config: { host: '127.0.0.1', port: 8878 },
    runtime,
    homeDir,
  });
  assert.equal(Number.isInteger(state.pid), true);
  assert.equal(processApi.readStatus({ homeDir }).running, true);
  await processApi.stopProcess({ homeDir });
  assert.equal(processApi.readStatus({ homeDir }).running, false);
  assert.equal(fs.existsSync(processApi.statePath(homeDir)), false);
  fs.rmSync(homeDir, { recursive: true, force: true });
});

test('lifecycle removes stale state without killing an unrelated process', async () => {
  const homeDir = home('stale');
  fs.mkdirSync(path.join(homeDir, '.media-bridge'), { recursive: true });
  fs.writeFileSync(processApi.statePath(homeDir), JSON.stringify({ pid: 999999, command: 'missing' }));
  const result = await processApi.stopProcess({ homeDir });
  assert.equal(result.running, false);
  assert.equal(fs.existsSync(processApi.statePath(homeDir)), false);
  fs.rmSync(homeDir, { recursive: true, force: true });
});

test('health returns stable JSON for success and network failure', async () => {
  const healthy = await processApi.checkHealth({
    config: { host: '127.0.0.1', port: 8878 },
    fetchImpl: async () => ({ ok: true, status: 200 }),
  });
  assert.deepEqual(healthy, { healthy: true, status: 200, url: 'http://127.0.0.1:8878/health' });
  const failed = await processApi.checkHealth({
    config: { host: '127.0.0.1', port: 8878 },
    fetchImpl: async () => { throw new Error('offline'); },
  });
  assert.deepEqual(failed, { healthy: false, status: null, url: 'http://127.0.0.1:8878/health' });
});
