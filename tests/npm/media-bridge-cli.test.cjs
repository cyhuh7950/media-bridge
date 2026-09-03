const test = require('node:test');
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const cli = path.resolve(__dirname, '../../packaging/npm/bin/mb.cjs');
const testRoot = process.env.MEDIA_BRIDGE_TEST_TMP || os.tmpdir();

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
  const tempHome = path.join(testRoot, 'media-bridge-npm-cli-home');
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
  assert.equal(typeof config.opencodex, 'object');
  assert.equal('apiKey' in config, false);
  fs.rmSync(tempHome, { recursive: true, force: true });
});

test('mb service install and uninstall manage only the Media Bridge service marker', () => {
  const tempHome = path.join(testRoot, 'media-bridge-npm-cli-service-home');
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

test('mb update prints the installed public package name', () => {
  const result = spawnSync(process.execPath, [cli, 'update'], { encoding: 'utf8' });
  assert.equal(result.status, 0);
  assert.equal(result.stdout, 'npm update -g @cyhuh/media-bridge 를 실행하십시오.\n');
});

function uninstallHome(name) {
  const tempHome = path.join(testRoot, `media-bridge-npm-uninstall-${name}`);
  fs.rmSync(tempHome, { recursive: true, force: true });
  const appDir = path.join(tempHome, '.media-bridge');
  fs.mkdirSync(path.join(appDir, 'runtime', 'bin'), { recursive: true });
  fs.mkdirSync(path.join(appDir, 'runtime-config'), { recursive: true });
  fs.writeFileSync(path.join(appDir, 'config.json'), '{"port":8765}\n');
  fs.writeFileSync(path.join(appDir, 'service.json'), '{"version":1}\n');
  fs.writeFileSync(path.join(appDir, 'runtime', 'bin', 'runtime.exe'), 'managed');
  fs.writeFileSync(path.join(appDir, 'runtime-config', 'service-token'), 'managed-secret');
  fs.writeFileSync(path.join(appDir, 'user-notes.txt'), 'not-owned-by-media-bridge');
  return { tempHome, appDir };
}

test('mb uninstall preserves config by default and removes only managed runtime state', () => {
  const { tempHome, appDir } = uninstallHome('keep-default');
  const result = spawnSync(process.execPath, [cli, 'uninstall'], {
    encoding: 'utf8',
    env: { ...process.env, HOME: tempHome, USERPROFILE: tempHome },
  });

  assert.equal(result.status, 0);
  assert.equal(fs.existsSync(path.join(appDir, 'config.json')), true);
  assert.equal(fs.existsSync(path.join(appDir, 'runtime')), false);
  assert.equal(fs.existsSync(path.join(appDir, 'runtime-config')), true);
  assert.equal(fs.existsSync(path.join(appDir, 'service.json')), false);
  assert.equal(fs.readFileSync(path.join(appDir, 'user-notes.txt'), 'utf8'), 'not-owned-by-media-bridge');
  assert.match(result.stdout, /설정을 보존했습니다/);
  assert.match(result.stdout, /npm uninstall -g @cyhuh\/media-bridge/);
  fs.rmSync(tempHome, { recursive: true, force: true });
});

test('mb uninstall --keep-config explicitly preserves config', () => {
  const { tempHome, appDir } = uninstallHome('keep-config');
  const result = spawnSync(process.execPath, [cli, 'uninstall', '--keep-config'], {
    encoding: 'utf8',
    env: { ...process.env, HOME: tempHome, USERPROFILE: tempHome },
  });

  assert.equal(result.status, 0);
  assert.equal(fs.existsSync(path.join(appDir, 'config.json')), true);
  assert.equal(fs.existsSync(path.join(appDir, 'runtime')), false);
  assert.equal(fs.existsSync(path.join(appDir, 'runtime-config')), true);
  assert.equal(fs.readFileSync(path.join(appDir, 'user-notes.txt'), 'utf8'), 'not-owned-by-media-bridge');
  assert.match(result.stdout, /설정을 보존했습니다/);
  fs.rmSync(tempHome, { recursive: true, force: true });
});

test('mb uninstall --delete-config deletes config but preserves unowned files', () => {
  const { tempHome, appDir } = uninstallHome('delete-config');
  const result = spawnSync(process.execPath, [cli, 'uninstall', '--delete-config'], {
    encoding: 'utf8',
    env: { ...process.env, HOME: tempHome, USERPROFILE: tempHome },
  });

  assert.equal(result.status, 0);
  assert.equal(fs.existsSync(path.join(appDir, 'config.json')), false);
  assert.equal(fs.existsSync(path.join(appDir, 'runtime')), false);
  assert.equal(fs.existsSync(path.join(appDir, 'runtime-config')), false);
  assert.equal(fs.existsSync(path.join(appDir, 'service.json')), false);
  assert.equal(fs.readFileSync(path.join(appDir, 'user-notes.txt'), 'utf8'), 'not-owned-by-media-bridge');
  assert.match(result.stdout, /설정을 삭제했습니다/);
  assert.match(result.stdout, /npm uninstall -g @cyhuh\/media-bridge/);
  fs.rmSync(tempHome, { recursive: true, force: true });
});

test('mb uninstall rejects conflicting config choices without deleting anything', () => {
  const { tempHome, appDir } = uninstallHome('conflicting-flags');
  const result = spawnSync(
    process.execPath,
    [cli, 'uninstall', '--keep-config', '--delete-config'],
    {
      encoding: 'utf8',
      env: { ...process.env, HOME: tempHome, USERPROFILE: tempHome },
    },
  );

  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /함께 사용할 수 없습니다/);
  assert.equal(fs.existsSync(path.join(appDir, 'config.json')), true);
  assert.equal(fs.existsSync(path.join(appDir, 'runtime')), true);
  assert.equal(fs.existsSync(path.join(appDir, 'service.json')), true);
  assert.equal(fs.existsSync(path.join(appDir, 'user-notes.txt')), true);
  fs.rmSync(tempHome, { recursive: true, force: true });
});
