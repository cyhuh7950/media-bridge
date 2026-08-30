const test = require('node:test');
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

const cli = path.resolve(__dirname, '../../packaging/npm/bin/mb.cjs');

test('mb help exposes the user install command surface', () => {
  const result = spawnSync(process.execPath, [cli, 'help'], { encoding: 'utf8' });
  assert.equal(result.status, 0);
  assert.match(result.stdout, /media-bridge init/);
  assert.match(result.stdout, /media-bridge start/);
  assert.match(result.stdout, /Compatibility alias: mb/);
  assert.match(result.stdout, /media-bridge health/);
  assert.match(result.stdout, /media-bridge service/);
});

test('mb init creates a local configuration without requiring a provider secret', () => {
  const tempHome = path.join(__dirname, '../../.tmp-npm-cli-home');
  fs.rmSync(tempHome, { recursive: true, force: true });
  const result = spawnSync(process.execPath, [cli, 'init'], {
    encoding: 'utf8',
    env: { ...process.env, HOME: tempHome, USERPROFILE: tempHome },
  });
  assert.equal(result.status, 0);
  assert.match(result.stdout, /initialized/i);
  const config = JSON.parse(fs.readFileSync(path.join(tempHome, '.media-bridge', 'config.json'), 'utf8'));
  assert.deepEqual(config.host, '127.0.0.1');
  assert.deepEqual(config.port, 8765);
  assert.equal(typeof config.openCodex, 'object');
  assert.equal('apiKey' in config, false);
  fs.rmSync(tempHome, { recursive: true, force: true });
});

test('mb service install and uninstall manage only the Media Bridge service marker', () => {
  const tempHome = path.join(__dirname, '../../.tmp-npm-cli-service-home');
  fs.rmSync(tempHome, { recursive: true, force: true });
  const env = { ...process.env, HOME: tempHome, USERPROFILE: tempHome };
  const run = (command) => spawnSync(process.execPath, [cli, ...command], { encoding: 'utf8', env });

  const install = run(['service', 'install']);
  assert.equal(install.status, 0);
  assert.match(install.stdout, /installed/i);
  assert.equal(fs.existsSync(path.join(tempHome, '.media-bridge', 'service.json')), true);

  const status = run(['service', 'status']);
  assert.equal(status.status, 0);
  assert.match(status.stdout, /stopped/i);

  const uninstall = run(['service', 'uninstall']);
  assert.equal(uninstall.status, 0);
  assert.match(uninstall.stdout, /uninstalled/i);
  assert.equal(fs.existsSync(path.join(tempHome, '.media-bridge', 'service.json')), false);
  fs.rmSync(tempHome, { recursive: true, force: true });
});
