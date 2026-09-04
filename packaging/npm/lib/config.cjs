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
    codingAgent: {
      preset: 'opencodex',
      protocol: 'openai-responses',
      baseUrl: 'http://127.0.0.1:8642/v1',
    },
    solar: {
      model: 'solar-pro4',
      endpoint: 'https://api.upstage.ai/v1/chat/completions',
      apiKeyEnv: 'SOLAR_API_KEY',
    },
    textLlm: {
      preset: 'upstage-solar',
      protocol: 'openai-chat-completions',
      endpoint: 'https://api.upstage.ai/v1/chat/completions',
      model: 'solar-pro4',
      credentialRef: 'text-llm',
      credentialEnv: 'SOLAR_API_KEY',
    },
    ocr: {
      endpoint: 'https://api.upstage.ai/v1/document-digitization',
      model: 'document-parse',
      apiKeyEnv: 'SOLAR_API_KEY',
    },
    mediaProcessor: {
      preset: 'upstage-document-parse',
      protocol: 'upstage-document-parse',
      endpoint: 'https://api.upstage.ai/v1/document-digitization',
      model: 'document-parse',
      credentialRef: 'media-processor',
      credentialEnv: 'SOLAR_API_KEY',
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
  config.codingAgent ??= {};
  config.solar ??= {};
  config.textLlm ??= {};
  config.ocr ??= {};
  config.mediaProcessor ??= {};
  config.conversion ??= {};
  config.failurePolicy ??= {};
  config.opencodex.baseUrl = validateEndpoint(config.opencodex.baseUrl, 'OpenCodex');
  config.codingAgent.baseUrl = validateEndpoint(config.codingAgent.baseUrl, 'coding agent');
  config.solar.endpoint = validateEndpoint(config.solar.endpoint, 'Solar');
  config.textLlm.endpoint = validateEndpoint(config.textLlm.endpoint, 'text LLM');
  config.ocr.endpoint = validateEndpoint(config.ocr.endpoint, 'OCR');
  config.mediaProcessor.endpoint = validateEndpoint(config.mediaProcessor.endpoint, 'media processor');
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
  if (!['opencodex', 'eoul-gateway', 'custom'].includes(config.codingAgent.preset)
      || config.codingAgent.protocol !== 'openai-responses') {
    throw new Error('coding agent preset or protocol is unsupported');
  }
  if (!['upstage-solar', 'custom'].includes(config.textLlm.preset)
      || !['openai-chat-completions', 'openai-responses'].includes(config.textLlm.protocol)
      || typeof config.textLlm.model !== 'string'
      || config.textLlm.model.trim() === ''
      || typeof config.textLlm.credentialRef !== 'string'
      || !/^[a-z0-9][a-z0-9._-]{0,63}$/.test(config.textLlm.credentialRef)
      || typeof config.textLlm.credentialEnv !== 'string'
      || !/^[A-Z_][A-Z0-9_]{0,127}$/.test(config.textLlm.credentialEnv)) {
    throw new Error('text LLM settings are invalid or unsupported');
  }
  if (config.mediaProcessor.preset !== 'upstage-document-parse'
      || config.mediaProcessor.protocol !== 'upstage-document-parse'
      || config.mediaProcessor.model !== 'document-parse'
      || typeof config.mediaProcessor.credentialRef !== 'string'
      || !/^[a-z0-9][a-z0-9._-]{0,63}$/.test(config.mediaProcessor.credentialRef)
      || typeof config.mediaProcessor.credentialEnv !== 'string'
      || !/^[A-Z_][A-Z0-9_]{0,127}$/.test(config.mediaProcessor.credentialEnv)) {
    throw new Error('media processor settings are invalid or unsupported');
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
    codingAgent: parsed.codingAgent
      ? { ...defaults.codingAgent, ...parsed.codingAgent }
      : {
        ...defaults.codingAgent,
        baseUrl: parsed.opencodex?.baseUrl || `http://${parsed.host || defaults.host}:${parsed.port || defaults.port}/v1`,
      },
    solar: { ...defaults.solar, ...parsed.solar },
    textLlm: parsed.textLlm
      ? { ...defaults.textLlm, ...parsed.textLlm }
      : {
        ...defaults.textLlm,
        endpoint: parsed.solar?.endpoint || defaults.solar.endpoint,
        model: parsed.solar?.model || defaults.solar.model,
        credentialEnv: parsed.solar?.apiKeyEnv || defaults.solar.apiKeyEnv,
      },
    ocr: { ...defaults.ocr, ...parsed.ocr },
    mediaProcessor: parsed.mediaProcessor
      ? { ...defaults.mediaProcessor, ...parsed.mediaProcessor }
      : {
        ...defaults.mediaProcessor,
        endpoint: parsed.ocr?.endpoint || defaults.ocr.endpoint,
        model: parsed.ocr?.model || defaults.ocr.model,
        credentialEnv: parsed.ocr?.apiKeyEnv || defaults.ocr.apiKeyEnv,
      },
    conversion: { ...defaults.conversion, ...parsed.conversion },
    failurePolicy: { ...defaults.failurePolicy, ...parsed.failurePolicy },
  };
  if (merged.opencodex.baseUrl === 'http://127.0.0.1:10100/v1') {
    merged.opencodex.baseUrl = `http://${merged.host}:${merged.port}/v1`;
    if (!parsed.codingAgent) merged.codingAgent.baseUrl = merged.opencodex.baseUrl;
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
  if (config.codingAgent?.baseUrl === previousOwnUrl) {
    config.codingAgent.baseUrl = `http://${config.host}:${port}/v1`;
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
