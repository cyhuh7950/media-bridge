const fs = require('node:fs');
const fsp = fs.promises;
const crypto = require('node:crypto');
const net = require('node:net');
const os = require('node:os');
const path = require('node:path');
const { execFileSync, spawn } = require('node:child_process');
const { configPath } = require('./config.cjs');

function statePath(homeDir = os.homedir()) {
  return path.join(homeDir, '.media-bridge', 'service.pid');
}

function stateDirectory(homeDir) {
  return path.dirname(statePath(homeDir));
}

async function removeManagedTree(target, {
  rmImpl = fsp.rm,
  sleepImpl = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds)),
  maxRetries = 100,
  retryDelay = 50,
} = {}) {
  const transientCodes = new Set(['EBUSY', 'EMFILE', 'ENFILE', 'ENOTEMPTY', 'EPERM']);
  for (let attempt = 0; ; attempt += 1) {
    try {
      await rmImpl(target, { recursive: true, force: true });
      return;
    } catch (error) {
      if (!transientCodes.has(error.code) || attempt >= maxRetries) throw error;
      await sleepImpl(retryDelay);
    }
  }
}

function writePrivateFileIfMissing(target, contents) {
  fs.mkdirSync(path.dirname(target), { recursive: true, mode: 0o700 });
  try {
    fs.writeFileSync(target, contents, { encoding: 'utf8', flag: 'wx', mode: 0o600 });
  } catch (error) {
    if (error.code !== 'EEXIST') throw error;
  }
  if (process.platform !== 'win32') fs.chmodSync(target, 0o600);
}

function prepareRuntimeEnvironment({ config, homeDir = os.homedir(), env = process.env } = {}) {
  const runtimeEnv = { ...env };
  const configRoot = path.join(stateDirectory(homeDir), 'runtime-config');
  const textLlm = config?.textLlm || {
    protocol: 'openai-chat-completions',
    endpoint: config?.solar?.endpoint,
    model: config?.solar?.model,
    credentialRef: 'text-llm',
    credentialEnv: config?.solar?.apiKeyEnv,
  };
  const mediaProcessor = config?.mediaProcessor || {
    protocol: 'upstage-document-parse',
    endpoint: config?.ocr?.endpoint,
    model: config?.ocr?.model,
    credentialRef: 'media-processor',
    credentialEnv: config?.ocr?.apiKeyEnv,
  };
  const model = textLlm.model || 'solar-pro4';
  const solarEndpoint = textLlm.endpoint || 'https://api.upstage.ai/v1/chat/completions';

  if (!runtimeEnv.MEDIA_BRIDGE_MODEL_REGISTRY) {
    const registryPath = path.join(configRoot, 'model-registry.yaml');
    fs.mkdirSync(configRoot, { recursive: true, mode: 0o700 });
    const temporary = `${registryPath}.${process.pid}.tmp`;
    const registry = [
      'version: "npm-personal-1"',
      'models:',
      `  - id: ${JSON.stringify(model)}`,
      '    input_modalities: [text]',
      '    expires_at: 2099-01-01T00:00:00Z',
      '    pdf_passthrough_verified: false',
      '',
    ].join('\n');
    fs.writeFileSync(temporary, registry, { encoding: 'utf8', mode: 0o600 });
    fs.renameSync(temporary, registryPath);
    if (process.platform !== 'win32') fs.chmodSync(registryPath, 0o600);
    runtimeEnv.MEDIA_BRIDGE_MODEL_REGISTRY = registryPath;
  }

  if (!runtimeEnv.MEDIA_BRIDGE_ASSET_ROOT) {
    runtimeEnv.MEDIA_BRIDGE_ASSET_ROOT = path.join(stateDirectory(homeDir), 'assets');
  }
  fs.mkdirSync(runtimeEnv.MEDIA_BRIDGE_ASSET_ROOT, { recursive: true, mode: 0o700 });

  if (!runtimeEnv.MEDIA_BRIDGE_RECEIPT_SECRET && !runtimeEnv.MEDIA_BRIDGE_RECEIPT_SECRET_FILE) {
    const secretFile = path.join(configRoot, 'receipt-secret');
    writePrivateFileIfMissing(secretFile, `${crypto.randomBytes(32).toString('base64')}\n`);
    runtimeEnv.MEDIA_BRIDGE_RECEIPT_SECRET_FILE = secretFile;
  }
  if (!runtimeEnv.MEDIA_BRIDGE_SERVICE_TOKEN && !runtimeEnv.MEDIA_BRIDGE_SERVICE_TOKEN_FILE) {
    const tokenFile = path.join(configRoot, 'service-token');
    writePrivateFileIfMissing(tokenFile, `${crypto.randomBytes(32).toString('base64url')}\n`);
    runtimeEnv.MEDIA_BRIDGE_SERVICE_TOKEN_FILE = tokenFile;
  }

  runtimeEnv.MEDIA_BRIDGE_RUNTIME_MODE = 'personal';
  runtimeEnv.MEDIA_BRIDGE_CREDENTIAL_STORE_FILE ||= path.join(stateDirectory(homeDir), 'secrets', 'providers.json');
  runtimeEnv.MEDIA_BRIDGE_TEXT_LLM_PROTOCOL ||= textLlm.protocol || 'openai-chat-completions';
  runtimeEnv.MEDIA_BRIDGE_TEXT_LLM_CREDENTIAL_REF ||= textLlm.credentialRef || 'text-llm';
  runtimeEnv.MEDIA_BRIDGE_MEDIA_PROCESSOR_PROTOCOL ||= mediaProcessor.protocol || 'upstage-document-parse';
  runtimeEnv.MEDIA_BRIDGE_MEDIA_PROCESSOR_CREDENTIAL_REF ||= mediaProcessor.credentialRef || 'media-processor';
  runtimeEnv.MEDIA_BRIDGE_OCR_ENDPOINT ||= mediaProcessor.endpoint || 'https://api.upstage.ai/v1/document-digitization';
  runtimeEnv.MEDIA_BRIDGE_OCR_CREDENTIAL_ENV ||= mediaProcessor.credentialEnv || textLlm.credentialEnv || 'SOLAR_API_KEY';
  runtimeEnv.MEDIA_BRIDGE_SOLAR_ENDPOINT ||= solarEndpoint;
  runtimeEnv.MEDIA_BRIDGE_SOLAR_MODEL ||= model;
  runtimeEnv.MEDIA_BRIDGE_SOLAR_CREDENTIAL_ENV ||= textLlm.credentialEnv || 'SOLAR_API_KEY';
  runtimeEnv.MEDIA_BRIDGE_MAX_REQUEST_BYTES ||= String(config?.conversion?.maxBytes || 8388608);
  runtimeEnv.MEDIA_BRIDGE_OCR_ENABLED ||= String(config?.conversion?.ocrEnabled !== false);
  runtimeEnv.MEDIA_BRIDGE_VISION_ENABLED ||= String(config?.conversion?.visionEnabled !== false);
  runtimeEnv.MEDIA_BRIDGE_BLOCK_SOLAR_ON_FAILURE ||= String(
    config?.failurePolicy?.blockSolarOnPreparationFailure !== false,
  );
  runtimeEnv.MEDIA_BRIDGE_CONFIG_FILE ||= configPath(homeDir);

  const configuredKey = runtimeEnv[textLlm.credentialEnv || 'SOLAR_API_KEY'];
  if (configuredKey) {
    runtimeEnv.SOLAR_API_KEY ||= configuredKey;
    runtimeEnv.MEDIA_BRIDGE_VISION_API_KEY ||= configuredKey;
    runtimeEnv.UPSTAGE_API_KEY ||= configuredKey;
  }
  return runtimeEnv;
}

function buildRuntimeArgs(runtime) {
  return runtime.python
    ? [
      ...(runtime.args || []),
      '-c',
      'from media_bridge_personal.npm_runtime import run_personal_npm_runtime; run_personal_npm_runtime()',
    ]
    : [...(runtime.args || [])];
}

function isAlive(pid) {
  if (!Number.isInteger(pid) || pid < 1) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

function inspectProcessIdentity(pid, platform = process.platform) {
  if (!isAlive(pid)) return null;
  try {
    if (platform === 'linux') {
      const stat = fs.readFileSync(`/proc/${pid}/stat`, 'utf8');
      const commandEnd = stat.lastIndexOf(')');
      const fieldsAfterCommand = stat.slice(commandEnd + 2).trim().split(/\s+/);
      const startMarker = fieldsAfterCommand[19];
      const executable = fs.readlinkSync(`/proc/${pid}/exe`);
      if (!startMarker || !executable) return null;
      return { executable, startMarker: `linux:${startMarker}` };
    }
    if (platform === 'win32') {
      const script = [
        `$p = Get-Process -Id ${pid} -ErrorAction Stop`,
        '$result = [ordered]@{ executable = $p.Path; startMarker = $p.StartTime.ToUniversalTime().Ticks.ToString() }',
        '$result | ConvertTo-Json -Compress',
      ].join('; ');
      const output = execFileSync('powershell.exe', [
        '-NoProfile', '-NonInteractive', '-Command', script,
      ], { encoding: 'utf8', windowsHide: true }).trim();
      const identity = JSON.parse(output);
      if (!identity.executable || !identity.startMarker) return null;
      return identity;
    }
    const output = execFileSync('ps', [
      '-p', String(pid), '-o', 'lstart=', '-o', 'comm=',
    ], { encoding: 'utf8' }).trim();
    const match = output.match(/^(.{24})\s+(.+)$/);
    if (!match) return null;
    return { executable: match[2].trim(), startMarker: `${platform}:${match[1].trim()}` };
  } catch {
    return null;
  }
}

function normalizedExecutable(value, platform = process.platform) {
  if (!value) return '';
  const normalized = path.normalize(value);
  return platform === 'win32' ? normalized.toLowerCase() : normalized;
}

function identityMatches(recorded, current, platform = process.platform) {
  if (!recorded || !current) return false;
  return recorded.startMarker === current.startMarker
    && normalizedExecutable(recorded.executable, platform) === normalizedExecutable(current.executable, platform);
}

function readState(homeDir) {
  const target = statePath(homeDir);
  if (!fs.existsSync(target)) return null;
  try {
    const state = JSON.parse(fs.readFileSync(target, 'utf8'));
    return Number.isInteger(state.pid) ? state : null;
  } catch {
    return null;
  }
}

async function writeState(homeDir, state) {
  await fsp.mkdir(stateDirectory(homeDir), { recursive: true, mode: 0o700 });
  const target = statePath(homeDir);
  const temporary = `${target}.${process.pid}.tmp`;
  await fsp.writeFile(temporary, `${JSON.stringify(state, null, 2)}\n`, { mode: 0o600 });
  await fsp.rename(temporary, target);
}

async function assertPortAvailable({ host, port, netImpl = net } = {}) {
  await new Promise((resolve, reject) => {
    const probe = netImpl.createServer();
    probe.once('error', (error) => {
      if (error.code === 'EADDRINUSE') {
        reject(new Error(`Media Bridge port ${host}:${port} is already in use by another process`));
        return;
      }
      reject(error);
    });
    probe.listen({ host, port, exclusive: true }, () => {
      probe.close((error) => error ? reject(error) : resolve());
    });
  });
}

async function startProcess({
  config,
  runtime,
  homeDir = os.homedir(),
  portOverride,
  startupGraceMs = 1000,
  sleepImpl = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds)),
} = {}) {
  const current = readStatus({ homeDir });
  if (current.running) throw new Error(`Media Bridge is already running: ${current.pid}`);
  const port = portOverride ?? config.port;
  await assertPortAvailable({ host: config.host, port });
  const args = buildRuntimeArgs(runtime);
  const child = spawn(runtime.command, args, {
    detached: true,
    stdio: 'ignore',
    env: {
      ...prepareRuntimeEnvironment({ config, homeDir, env: runtime.env }),
      MEDIA_BRIDGE_HTTP_HOST: config.host,
      MEDIA_BRIDGE_HTTP_PORT: String(port),
    },
  });
  try {
    await new Promise((resolve, reject) => {
      child.once('spawn', resolve);
      child.once('error', reject);
    });
    const identity = inspectProcessIdentity(child.pid);
    if (!identity) throw new Error('Media Bridge child identity could not be verified');
    const state = { pid: child.pid, command: runtime.command, identity, host: config.host, port };
    await writeState(homeDir, state);
    await sleepImpl(startupGraceMs);
    if (!identityMatches(identity, inspectProcessIdentity(child.pid))) {
      throw new Error('Media Bridge process exited during startup');
    }
    child.unref();
    return state;
  } catch (error) {
    if (child.pid && isAlive(child.pid)) child.kill();
    await fsp.rm(statePath(homeDir), { force: true });
    throw error;
  }
}

async function startManagedRuntime({
  config,
  homeDir = os.homedir(),
  portOverride,
  readStatusImpl = readStatus,
  resolveRuntimeImpl,
  startProcessImpl = startProcess,
} = {}) {
  const current = readStatusImpl({ homeDir });
  if (current.running) throw new Error(`Media Bridge is already running: ${current.pid}`);
  const runtime = await resolveRuntimeImpl({ homeDir });
  return startProcessImpl({ config, runtime, homeDir, portOverride });
}

async function stopProcess({
  homeDir = os.homedir(),
  platform = process.platform,
  isAliveImpl = isAlive,
  inspectIdentity = inspectProcessIdentity,
  killImpl = process.kill,
  sleepImpl = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds)),
  stopTimeoutMs = 5000,
} = {}) {
  const state = readState(homeDir);
  if (!state) return { running: false };
  if (isAliveImpl(state.pid)) {
    const currentIdentity = inspectIdentity(state.pid, platform);
    if (!identityMatches(state.identity, currentIdentity, platform)) {
      await fsp.rm(statePath(homeDir), { force: true });
      return { running: false, pid: state.pid, ownershipMismatch: true };
    }
    try { killImpl(state.pid); } catch { /* process exited between checks */ }
    const deadline = Date.now() + stopTimeoutMs;
    while (isAliveImpl(state.pid) && Date.now() < deadline) {
      await sleepImpl(50);
    }
    if (isAliveImpl(state.pid)) {
      throw new Error(`Media Bridge process did not stop within ${stopTimeoutMs}ms: ${state.pid}`);
    }
  }
  await fsp.rm(statePath(homeDir), { force: true });
  return { running: false, pid: state.pid };
}

function readStatus({
  homeDir = os.homedir(),
  platform = process.platform,
  isAliveImpl = isAlive,
  inspectIdentity = inspectProcessIdentity,
} = {}) {
  const state = readState(homeDir);
  if (!state) return { running: false };
  const running = isAliveImpl(state.pid);
  if (!running) fs.rmSync(statePath(homeDir), { force: true });
  if (!running) return { running: false };
  const currentIdentity = inspectIdentity(state.pid, platform);
  if (!identityMatches(state.identity, currentIdentity, platform)) {
    fs.rmSync(statePath(homeDir), { force: true });
    return { running: false, ownershipMismatch: true };
  }
  return { ...state, running: true };
}

async function checkHealth({ config, fetchImpl = fetch } = {}) {
  const url = `http://${config.host}:${config.port}/health`;
  try {
    const response = await fetchImpl(url);
    return { healthy: response.ok, status: response.status, url };
  } catch {
    return { healthy: false, status: null, url };
  }
}

async function checkManagedHealth({
  config,
  homeDir = os.homedir(),
  fetchImpl = fetch,
  readStatusImpl = readStatus,
} = {}) {
  const url = `http://${config.host}:${config.port}/health`;
  if (!readStatusImpl({ homeDir }).running) {
    return { healthy: false, status: null, url, reason: 'service_not_running' };
  }
  return checkHealth({ config, fetchImpl });
}

module.exports = {
  assertPortAvailable,
  buildRuntimeArgs,
  checkHealth,
  checkManagedHealth,
  identityMatches,
  inspectProcessIdentity,
  isAlive,
  prepareRuntimeEnvironment,
  readStatus,
  removeManagedTree,
  startManagedRuntime,
  startProcess,
  statePath,
  stopProcess,
};
