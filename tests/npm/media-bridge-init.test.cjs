const test = require('node:test');
const assert = require('node:assert/strict');
const { defaultConfig } = require('../../packaging/npm/lib/config.cjs');
const { parseNonInteractiveConfig, runWizard } = require('../../packaging/npm/lib/wizard.cjs');

test('init wizard stores OpenCodex, port, Solar, conversion, and failure policy', async () => {
  const answers = [
    'http://127.0.0.1:8876/v1',
    '8876',
    'solar-pro4',
    'https://solar.example.invalid/v1/chat/completions',
    'SOLAR_API_KEY',
    'https://ocr.example.invalid/v1/document-digitization',
    'SOLAR_API_KEY',
    '8388608',
    'y',
    'y',
    'y',
  ];
  const config = await runWizard({
    existingConfig: defaultConfig(),
    ask: async () => answers.shift(),
  });
  assert.equal(config.opencodex.baseUrl, 'http://127.0.0.1:8876/v1');
  assert.equal(config.port, 8876);
  assert.equal(config.solar.model, 'solar-pro4');
  assert.equal(config.solar.apiKeyEnv, 'SOLAR_API_KEY');
  assert.equal(config.ocr.endpoint, 'https://ocr.example.invalid/v1/document-digitization');
  assert.equal(config.ocr.apiKeyEnv, 'SOLAR_API_KEY');
  assert.equal(config.conversion.maxBytes, 8388608);
  assert.equal(config.failurePolicy.blockSolarOnPreparationFailure, true);
});

test('init wizard rejects invalid port and endpoint without accepting unsafe values', async () => {
  const answers = ['http://example.com/v1', '0'];
  await assert.rejects(() => runWizard({
    existingConfig: defaultConfig(),
    ask: async () => answers.shift(),
  }), /loopback|port/i);
});

test('non-interactive init accepts MB settings without storing Secret values', () => {
  const config = parseNonInteractiveConfig({
    MB_OPEN_CODEX_URL: 'http://127.0.0.1:8877/v1',
    MB_PORT: '8877',
    MB_SOLAR_MODEL: 'solar-mini',
    MB_SOLAR_ENDPOINT: 'https://solar.example.invalid/v1',
    MB_SOLAR_API_KEY_ENV: 'SOLAR_API_KEY',
    MB_OCR_ENDPOINT: 'https://ocr.example.invalid/v1/document-digitization',
    MB_OCR_API_KEY_ENV: 'UPSTAGE_API_KEY',
    MB_CONVERSION_MAX_BYTES: '4096',
    MB_OCR_ENABLED: 'false',
    MB_VISION_ENABLED: 'true',
    MB_BLOCK_SOLAR_ON_FAILURE: 'true',
  }, defaultConfig());
  assert.equal(config.port, 8877);
  assert.equal(config.solar.model, 'solar-mini');
  assert.equal(config.ocr.endpoint, 'https://ocr.example.invalid/v1/document-digitization');
  assert.equal(config.ocr.apiKeyEnv, 'UPSTAGE_API_KEY');
  assert.equal(config.conversion.ocrEnabled, false);
  assert.equal(config.conversion.visionEnabled, true);
  assert.equal('apiKey' in config.solar, false);
});
