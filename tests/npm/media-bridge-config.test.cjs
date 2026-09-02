const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const {
  defaultConfig,
  loadConfig,
  saveConfig,
  validateConfig,
} = require('../../packaging/npm/lib/config.cjs');

function home(name) {
  const value = path.join(process.env.MEDIA_BRIDGE_TEST_TMP || os.tmpdir(), `media-bridge-npm-config-${name}`);
  fs.rmSync(value, { recursive: true, force: true });
  return value;
}

test('default config contains fail-closed conversion settings', () => {
  const config = defaultConfig();
  assert.equal(config.host, '127.0.0.1');
  assert.equal(config.port, 8765);
  assert.equal(config.failurePolicy.blockSolarOnPreparationFailure, true);
  assert.equal(config.conversion.ocrEnabled, true);
  assert.equal(config.conversion.visionEnabled, true);
});

test('config is saved with private permissions and loaded without secrets', () => {
  const tempHome = home('permissions');
  const config = defaultConfig();
  config.solar.apiKeyEnv = 'SOLAR_API_KEY';
  const configPath = saveConfig({ homeDir: tempHome, config });
  if (process.platform !== 'win32') {
    const directoryMode = fs.statSync(path.dirname(configPath)).mode & 0o777;
    const fileMode = fs.statSync(configPath).mode & 0o777;
    assert.equal(directoryMode, 0o700);
    assert.equal(fileMode, 0o600);
  }
  assert.equal(loadConfig({ homeDir: tempHome }).solar.apiKeyEnv, 'SOLAR_API_KEY');
  assert.equal('apiKey' in loadConfig({ homeDir: tempHome }).solar, false);
  fs.rmSync(tempHome, { recursive: true, force: true });
});

test('validation rejects non-loopback HTTP and invalid ports', () => {
  assert.throws(() => validateConfig({ ...defaultConfig(), port: 0 }), /port/i);
  assert.throws(() => validateConfig({
    ...defaultConfig(),
    opencodex: { baseUrl: 'http://example.com/v1' },
  }), /HTTPS|loopback/i);
});

test('save config writes atomically and preserves full configuration fields', () => {
  const tempHome = home('round-trip');
  const config = defaultConfig();
  config.opencodex.baseUrl = 'http://127.0.0.1:10100/v1';
  config.solar.model = 'solar-pro4';
  config.solar.endpoint = 'https://solar.example.invalid/v1';
  const configPath = saveConfig({ homeDir: tempHome, config });
  const loaded = loadConfig({ homeDir: tempHome });
  assert.deepEqual(loaded, config);
  assert.equal(fs.existsSync(`${configPath}.tmp`), false);
  fs.rmSync(tempHome, { recursive: true, force: true });
});
