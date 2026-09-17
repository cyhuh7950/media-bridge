const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

function tempHome(name) {
  const home = path.join(os.tmpdir(), `media-bridge-autostart-${name}-${process.pid}`);
  fs.rmSync(home, { recursive: true, force: true });
  fs.mkdirSync(home, { recursive: true });
  return home;
}

test('service install registers a reboot start hook and persists enabled state', () => {
  const home = tempHome('install');
  try {
    const result = spawnSync(process.execPath, [path.resolve(__dirname, '../../packaging/npm/bin/mb.cjs'), 'service', 'install'], {
      env: { ...process.env, USERPROFILE: home, HOME: home, APPDATA: path.join(home, 'AppData', 'Roaming') },
      encoding: 'utf8',
    });
    assert.equal(result.status, 0, result.stderr);
    const service = JSON.parse(fs.readFileSync(path.join(home, '.media-bridge', 'service.json'), 'utf8'));
    assert.equal(service.enabled, true);
    assert.ok(fs.existsSync(path.join(home, '.config', 'systemd', 'user', 'media-bridge.service')) || fs.existsSync(path.join(home, '.profile')) || fs.existsSync(path.join(home, 'AppData', 'Roaming', 'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Startup', 'Media Bridge.cmd')));
  } finally {
    fs.rmSync(home, { recursive: true, force: true });
  }
});

test('start upgrades an old service marker instead of requiring manual repair', () => {
  const home = tempHome('upgrade');
  try {
    fs.mkdirSync(path.join(home, '.media-bridge'), { recursive: true });
    fs.writeFileSync(path.join(home, '.media-bridge', 'service.json'), JSON.stringify({ version: 1, enabled: false }));
    const result = spawnSync(process.execPath, [path.resolve(__dirname, '../../packaging/npm/bin/mb.cjs'), 'start'], {
      env: { ...process.env, USERPROFILE: home, HOME: home, APPDATA: path.join(home, 'AppData', 'Roaming'), MEDIA_BRIDGE_TEST_MODE: '1' },
      encoding: 'utf8',
    });
    const marker = JSON.parse(fs.readFileSync(path.join(home, '.media-bridge', 'service.json'), 'utf8'));
    assert.equal(marker.enabled, true);
    assert.notEqual(result.status, 0);
  } finally {
    fs.rmSync(home, { recursive: true, force: true });
  }
});
