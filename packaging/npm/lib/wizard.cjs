const { defaultConfig, validateConfig } = require('./config.cjs');

function valueOrDefault(value, fallback) {
  return value === undefined || value === '' ? fallback : value;
}

function booleanValue(value, fallback) {
  if (value === undefined || value === '') return fallback;
  if (/^(y|yes|true|1)$/i.test(value)) return true;
  if (/^(n|no|false|0)$/i.test(value)) return false;
  throw new Error(`boolean value is invalid: ${value}`);
}

function syncRoleConfig(config) {
  config.codingAgent = {
    preset: 'opencodex',
    protocol: 'openai-responses',
    baseUrl: config.opencodex.baseUrl,
  };
  config.textLlm = {
    preset: 'upstage-solar',
    protocol: 'openai-chat-completions',
    endpoint: config.solar.endpoint,
    model: config.solar.model,
    credentialRef: config.textLlm?.credentialRef || 'text-llm',
    credentialEnv: config.solar.apiKeyEnv,
  };
  config.mediaProcessor = {
    preset: 'upstage-document-parse',
    protocol: 'upstage-document-parse',
    endpoint: config.ocr.endpoint,
    model: 'document-parse',
    credentialRef: config.mediaProcessor?.credentialRef || 'media-processor',
    credentialEnv: config.ocr.apiKeyEnv,
  };
  return config;
}

function parseNonInteractiveConfig(env, existingConfig = defaultConfig()) {
  const config = structuredClone(existingConfig);
  config.opencodex.baseUrl = valueOrDefault(env.MB_OPEN_CODEX_URL, config.opencodex.baseUrl);
  config.port = Number(valueOrDefault(env.MB_PORT, config.port));
  config.solar.model = valueOrDefault(env.MB_SOLAR_MODEL, config.solar.model);
  config.solar.endpoint = valueOrDefault(env.MB_SOLAR_ENDPOINT, config.solar.endpoint);
  config.solar.apiKeyEnv = valueOrDefault(env.MB_SOLAR_API_KEY_ENV, config.solar.apiKeyEnv);
  config.ocr.endpoint = valueOrDefault(env.MB_OCR_ENDPOINT, config.ocr.endpoint);
  config.ocr.apiKeyEnv = valueOrDefault(env.MB_OCR_API_KEY_ENV, config.ocr.apiKeyEnv);
  config.conversion.maxBytes = Number(valueOrDefault(env.MB_CONVERSION_MAX_BYTES, config.conversion.maxBytes));
  config.conversion.ocrEnabled = booleanValue(env.MB_OCR_ENABLED, config.conversion.ocrEnabled);
  config.conversion.visionEnabled = booleanValue(env.MB_VISION_ENABLED, config.conversion.visionEnabled);
  config.failurePolicy.blockSolarOnPreparationFailure = booleanValue(
    env.MB_BLOCK_SOLAR_ON_FAILURE,
    config.failurePolicy.blockSolarOnPreparationFailure,
  );
  return validateConfig(syncRoleConfig(config));
}

async function runWizard({ ask, existingConfig = defaultConfig() }) {
  const config = structuredClone(existingConfig);
  const answer = async (question, fallback) => valueOrDefault(await ask(question, fallback), fallback);
  config.opencodex.baseUrl = await answer('OpenCodex에 설정할 Media Bridge 주소', config.opencodex.baseUrl);
  config.port = Number(await answer('Media Bridge 포트', config.port));
  config.solar.model = await answer('Solar 모델 이름', config.solar.model);
  config.solar.endpoint = await answer('Solar 연결 주소', config.solar.endpoint);
  config.solar.apiKeyEnv = await answer('Solar API key 환경변수 이름', config.solar.apiKeyEnv);
  config.ocr.endpoint = await answer('Upstage Document Parse 연결 주소', config.ocr.endpoint);
  config.ocr.apiKeyEnv = await answer('Document Parse API key 환경변수 이름', config.ocr.apiKeyEnv);
  config.conversion.maxBytes = Number(await answer('변환 최대 크기(bytes)', config.conversion.maxBytes));
  config.conversion.ocrEnabled = booleanValue(await answer('OCR 변환 사용 (y/n)', config.conversion.ocrEnabled ? 'y' : 'n'), config.conversion.ocrEnabled);
  config.conversion.visionEnabled = booleanValue(await answer('Vision 변환 사용 (y/n)', config.conversion.visionEnabled ? 'y' : 'n'), config.conversion.visionEnabled);
  config.failurePolicy.blockSolarOnPreparationFailure = booleanValue(
    await answer('변환 실패 시 Solar 전송 차단 (y/n)', config.failurePolicy.blockSolarOnPreparationFailure ? 'y' : 'n'),
    config.failurePolicy.blockSolarOnPreparationFailure,
  );
  return validateConfig(syncRoleConfig(config));
}

module.exports = {
  parseNonInteractiveConfig,
  runWizard,
};
