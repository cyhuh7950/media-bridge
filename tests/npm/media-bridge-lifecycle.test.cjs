const test = require('node:test');
const assert = require('node:assert/strict');
const { once } = require('node:events');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
const processApi = require('../../packaging/npm/lib/process.cjs');

function home(name) {
  const value = path.join(process.env.MEDIA_BRIDGE_TEST_TMP || os.tmpdir(), `media-bridge-npm-lifecycle-${name}`);
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
  assert.equal(typeof state.identity.startMarker, 'string');
  assert.equal(typeof state.identity.executable, 'string');
  assert.equal(processApi.readStatus({ homeDir }).running, true);
  await processApi.stopProcess({ homeDir });
  assert.equal(processApi.readStatus({ homeDir }).running, false);
  assert.equal(fs.existsSync(processApi.statePath(homeDir)), false);
  fs.rmSync(homeDir, { recursive: true, force: true });
});

test('lifecycle refuses to kill a live process when recorded ownership does not match', async () => {
  const homeDir = home('ownership-mismatch');
  const unrelated = spawn(process.execPath, ['-e', 'setInterval(() => {}, 1000)'], {
    detached: false,
    stdio: 'ignore',
  });
  await once(unrelated, 'spawn');
  try {
    fs.mkdirSync(path.join(homeDir, '.media-bridge'), { recursive: true });
    fs.writeFileSync(processApi.statePath(homeDir), JSON.stringify({
      pid: unrelated.pid,
      command: process.execPath,
      identity: { executable: process.execPath, startMarker: 'not-the-current-process' },
    }));
    const result = await processApi.stopProcess({ homeDir });
    assert.equal(result.ownershipMismatch, true);
    assert.equal(processApi.isAlive(unrelated.pid), true);
    assert.equal(fs.existsSync(processApi.statePath(homeDir)), false);
  } finally {
    if (processApi.isAlive(unrelated.pid)) unrelated.kill();
    fs.rmSync(homeDir, { recursive: true, force: true });
  }
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
