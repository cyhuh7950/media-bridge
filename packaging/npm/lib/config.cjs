const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

function defaultConfig() {
  return {
    runtimeMode: 'personal',
    host: '127.0.0.1',
    port: 8642,
    opencodex: {
      baseUrl: 'http://127.0.0.1:8642/v1',
    },
    solar: {
      model: 'solar-pro4',
      endpoint: 'https://api.upstage.ai/v1/chat/completions',
      apiKeyEnv: 'SOLAR_API_KEY',
    },
    ocr: {
      endpoint: 'https://api.upstage.ai/v1/document-digitization',
      model: 'document-parse',
      apiKeyEnv: 'SOLAR_API_KEY',
    },
    conversion: {
      maxBytes: 8388608,
      ocrEnabled: true,
      visionEnabled: true,
    },
    failurePolicy: {
      blockSolarOnPreparationFailure: true,
    },
  };
}

function configPath(homeDir = os.homedir()) {
  return path.join(homeDir, '.media-bridge', 'config.json');
}

function isLoopback(hostname) {
  return hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '[::1]' || hostname === '::1';
}

function validateEndpoint(value, field) {
  if (typeof value !== 'string' || value.length === 0) {
    throw new Error(`${field} endpoint is required`);
  }
  let parsed;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error(`${field} endpoint must be a valid URL`);
  }
  if (parsed.protocol !== 'https:' && !(parsed.protocol === 'http:' && isLoopback(parsed.hostname))) {
    throw new Error(`${field} endpoint must use HTTPS or loopback`);
  }
  return value;
}

function validateConfig(input) {
  const config = structuredClone(input);
  if (!Number.isInteger(config.port) || config.port < 1 || config.port > 65535) {
    throw new Error('port must be an integer from 1 to 65535');
  }
  if (typeof config.host !== 'string' || !isLoopback(config.host)) {
    throw new Error('host must be a loopback address');
  }
  config.opencodex ??= {};
  config.solar ??= {};
  config.ocr ??= {};
  config.conversion ??= {};
  config.failurePolicy ??= {};
  config.opencodex.baseUrl = validateEndpoint(config.opencodex.baseUrl, 'OpenCodex');
  config.solar.endpoint = validateEndpoint(config.solar.endpoint, 'Solar');
  config.ocr.endpoint = validateEndpoint(config.ocr.endpoint, 'OCR');
  if (config.runtimeMode !== 'personal') {
    throw new Error('npm runtime mode must be personal');
  }
  if (typeof config.solar.model !== 'string' || config.solar.model.trim() === '') {
    throw new Error('Solar model is required');
  }
  if (typeof config.solar.apiKeyEnv !== 'string' || config.solar.apiKeyEnv.trim() === '') {
    throw new Error('Solar API key environment reference is required');
  }
  if (config.ocr.model !== 'document-parse') {
    throw new Error('OCR model must be document-parse');
  }
  if (typeof config.ocr.apiKeyEnv !== 'string' || config.ocr.apiKeyEnv.trim() === '') {
    throw new Error('OCR API key environment reference is required');
  }
  if (!Number.isInteger(config.conversion.maxBytes) || config.conversion.maxBytes < 1) {
    throw new Error('conversion maxBytes must be a positive integer');
  }
  config.conversion.ocrEnabled = Boolean(config.conversion.ocrEnabled);
  config.conversion.visionEnabled = Boolean(config.conversion.visionEnabled);
  config.failurePolicy.blockSolarOnPreparationFailure = Boolean(
    config.failurePolicy.blockSolarOnPreparationFailure,
  );
  return config;
}

function loadConfig({ homeDir = os.homedir() } = {}) {
  const target = configPath(homeDir);
  if (!fs.existsSync(target)) return defaultConfig();
  let parsed;
  try {
    parsed = JSON.parse(fs.readFileSync(target, 'utf8'));
  } catch {
    throw new Error(`config file is not valid JSON: ${target}`);
  }
  const defaults = defaultConfig();
  const merged = {
    ...defaults,
    ...parsed,
    opencodex: { ...defaults.opencodex, ...parsed.opencodex },
    solar: { ...defaults.solar, ...parsed.solar },
    ocr: { ...defaults.ocr, ...parsed.ocr },
    conversion: { ...defaults.conversion, ...parsed.conversion },
    failurePolicy: { ...defaults.failurePolicy, ...parsed.failurePolicy },
  };
  if (merged.opencodex.baseUrl === 'http://127.0.0.1:10100/v1') {
    merged.opencodex.baseUrl = `http://${merged.host}:${merged.port}/v1`;
  }
  return validateConfig(merged);
}

function applyPortOverride(input, port) {
  const config = structuredClone(input);
  const previousOwnUrl = `http://${config.host}:${config.port}/v1`;
  config.port = port;
  if (config.opencodex?.baseUrl === previousOwnUrl) {
    config.opencodex.baseUrl = `http://${config.host}:${port}/v1`;
  }
  return validateConfig(config);
}

function saveConfig({ homeDir = os.homedir(), config }) {
  const validated = validateConfig(config);
  const directory = path.dirname(configPath(homeDir));
  fs.mkdirSync(directory, { recursive: true, mode: 0o700 });
  fs.chmodSync(directory, 0o700);
  const target = configPath(homeDir);
  const temporary = `${target}.${process.pid}.tmp`;
  fs.writeFileSync(temporary, `${JSON.stringify(validated, null, 2)}\n`, { mode: 0o600 });
  fs.chmodSync(temporary, 0o600);
  fs.renameSync(temporary, target);
  fs.chmodSync(target, 0o600);
  return target;
}

module.exports = {
  applyPortOverride,
  configPath,
  defaultConfig,
  loadConfig,
  saveConfig,
  validateConfig,
};
