const test = require('node:test');
const assert = require('node:assert/strict');

const { openGui } = require('../../packaging/npm/lib/gui.cjs');

test('gui opens the loopback settings page on desktop platforms', () => {
  const calls = [];
  const child = { on() {}, unref() {} };
  const opened = openGui('http://127.0.0.1:8765/', {
    platform: 'win32',
    env: {},
    spawnImpl: (...args) => { calls.push(args); return child; },
  });
  assert.equal(opened, true);
  assert.equal(calls[0][0], 'explorer.exe');
  assert.deepEqual(calls[0][1], ['http://127.0.0.1:8765/']);
});

test('gui remains usable by URL on a headless Linux server', () => {
  let spawned = false;
  const opened = openGui('http://127.0.0.1:8765/', {
    platform: 'linux',
    env: {},
    spawnImpl: () => { spawned = true; throw new Error('must not spawn'); },
  });
  assert.equal(opened, false);
  assert.equal(spawned, false);
});
