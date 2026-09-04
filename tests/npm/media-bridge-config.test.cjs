const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const {
  applyPortOverride,
  defaultConfig,
  loadConfig,
  saveConfig,
  validateConfig,
} = require('../../packaging/npm/lib/config.cjs');

test('port override keeps health and gui config on the active listener', () => {
  const updated = applyPortOverride(defaultConfig(), 8877);
  assert.equal(updated.port, 8877);
  assert.equal(updated.opencodex.baseUrl, 'http://127.0.0.1:8877/v1');
  assert.throws(() => applyPortOverride(defaultConfig(), 0), /port/i);
});

function home(name) {
  const value = path.join(process.env.MEDIA_BRIDGE_TEST_TMP || os.tmpdir(), `media-bridge-npm-config-${name}`);
  fs.rmSync(value, { recursive: true, force: true });
  return value;
}

test('default config contains fail-closed conversion settings', () => {
  const config = defaultConfig();
  assert.equal(config.host, '127.0.0.1');
  assert.equal(config.port, 8642);
  assert.equal(config.opencodex.baseUrl, 'http://127.0.0.1:8642/v1');
  assert.equal(config.runtimeMode, 'personal');
  assert.equal(config.ocr.endpoint, 'https://api.upstage.ai/v1/document-digitization');
  assert.equal(config.ocr.model, 'document-parse');
  assert.equal(config.ocr.apiKeyEnv, 'SOLAR_API_KEY');
  assert.equal(config.failurePolicy.blockSolarOnPreparationFailure, true);
  assert.equal(config.conversion.ocrEnabled, true);
  assert.equal(config.conversion.visionEnabled, true);
  assert.deepEqual(config.codingAgent, {
    preset: 'opencodex',
    protocol: 'openai-responses',
    baseUrl: 'http://127.0.0.1:8642/v1',
  });
  assert.deepEqual(config.textLlm, {
    preset: 'upstage-solar',
    protocol: 'openai-chat-completions',
    endpoint: 'https://api.upstage.ai/v1/chat/completions',
    model: 'solar-pro4',
    credentialRef: 'text-llm',
    credentialEnv: 'SOLAR_API_KEY',
  });
  assert.deepEqual(config.mediaProcessor, {
    preset: 'upstage-document-parse',
    protocol: 'upstage-document-parse',
    endpoint: 'https://api.upstage.ai/v1/document-digitization',
    model: 'document-parse',
    credentialRef: 'media-processor',
    credentialEnv: 'SOLAR_API_KEY',
  });
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
  config.opencodex.baseUrl = 'http://127.0.0.1:8876/v1';
  config.solar.model = 'solar-pro4';
  config.solar.endpoint = 'https://solar.example.invalid/v1';
  config.ocr.endpoint = 'https://ocr.example.invalid/v1/document-digitization';
  const configPath = saveConfig({ homeDir: tempHome, config });
  const loaded = loadConfig({ homeDir: tempHome });
  assert.deepEqual(loaded, config);
  assert.equal(fs.existsSync(`${configPath}.tmp`), false);
  fs.rmSync(tempHome, { recursive: true, force: true });
});

test('loading migrates the legacy OpenCodex server address to the Media Bridge provider URL', () => {
  const tempHome = home('legacy-opencodex-address');
  const legacy = defaultConfig();
  legacy.opencodex.baseUrl = 'http://127.0.0.1:10100/v1';
  fs.mkdirSync(path.dirname(path.join(tempHome, '.media-bridge', 'config.json')), { recursive: true });
  fs.writeFileSync(
    path.join(tempHome, '.media-bridge', 'config.json'),
    `${JSON.stringify(legacy)}\n`,
  );

  const loaded = loadConfig({ homeDir: tempHome });

  assert.equal(loaded.opencodex.baseUrl, 'http://127.0.0.1:8642/v1');
  fs.rmSync(tempHome, { recursive: true, force: true });
});

test('loading an older partial config fills the new personal runtime defaults', () => {
  const tempHome = home('legacy-partial');
  const target = path.join(tempHome, '.media-bridge', 'config.json');
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(target, JSON.stringify({
    host: '127.0.0.1',
    port: 8877,
    opencodex: { baseUrl: 'http://127.0.0.1:10100/v1' },
    solar: { model: 'solar-pro4' },
  }));

  const loaded = loadConfig({ homeDir: tempHome });

  assert.equal(loaded.opencodex.baseUrl, 'http://127.0.0.1:8877/v1');
  assert.equal(loaded.solar.endpoint, 'https://api.upstage.ai/v1/chat/completions');
  assert.equal(loaded.ocr.model, 'document-parse');
  assert.equal(loaded.failurePolicy.blockSolarOnPreparationFailure, true);
  assert.equal(loaded.codingAgent.preset, 'opencodex');
  assert.equal(loaded.textLlm.model, 'solar-pro4');
  assert.equal(loaded.textLlm.endpoint, 'https://api.upstage.ai/v1/chat/completions');
  assert.equal(loaded.mediaProcessor.protocol, 'upstage-document-parse');
  fs.rmSync(tempHome, { recursive: true, force: true });
});

test('generic provider settings round-trip without storing API key material', () => {
  const tempHome = home('generic-provider');
  const config = defaultConfig();
  config.codingAgent = {
    preset: 'eoul-gateway',
    protocol: 'openai-responses',
    baseUrl: 'http://127.0.0.1:8642/v1',
  };
  config.textLlm = {
    preset: 'custom',
    protocol: 'openai-responses',
    endpoint: 'https://llm.example.test/v1/responses',
    model: 'text-model',
    credentialRef: 'text-llm',
    credentialEnv: 'CUSTOM_LLM_KEY',
  };
  config.mediaProcessor = {
    preset: 'upstage-document-parse',
    protocol: 'upstage-document-parse',
    endpoint: 'https://api.upstage.ai/v1/document-digitization',
    model: 'document-parse',
    credentialRef: 'media-processor',
    credentialEnv: 'UPSTAGE_API_KEY',
  };

  saveConfig({ homeDir: tempHome, config });
  const loaded = loadConfig({ homeDir: tempHome });

  assert.deepEqual(loaded.codingAgent, config.codingAgent);
  assert.deepEqual(loaded.textLlm, config.textLlm);
  assert.deepEqual(loaded.mediaProcessor, config.mediaProcessor);
  assert.doesNotMatch(fs.readFileSync(configPathFor(tempHome), 'utf8'), /actual-secret/);
  fs.rmSync(tempHome, { recursive: true, force: true });
});

function configPathFor(homeDir) {
  return path.join(homeDir, '.media-bridge', 'config.json');
}
