const test = require('node:test');
const assert = require('node:assert/strict');
const { once } = require('node:events');
const fs = require('node:fs');
const net = require('node:net');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
const processApi = require('../../packaging/npm/lib/process.cjs');

function home(name) {
  const value = path.join(process.env.MEDIA_BRIDGE_TEST_TMP || os.tmpdir(), `media-bridge-npm-lifecycle-${name}`);
  fs.rmSync(value, { recursive: true, force: true });
  fs.mkdirSync(value, { recursive: true });
  return value;
}

test('start orchestration checks the tracked service before resolving a runtime update', async () => {
  let resolved = false;
  await assert.rejects(() => processApi.startManagedRuntime({
    config: { host: '127.0.0.1', port: 8878 },
    homeDir: home('pre-resolve-running'),
    readStatusImpl: () => ({ running: true, pid: 44001 }),
    resolveRuntimeImpl: async () => {
      resolved = true;
      throw new Error('runtime resolver must not run');
    },
  }), /already running.*44001/i);
  assert.equal(resolved, false);
});

test('start rejects a port already owned by an unmanaged listener', async () => {
  const homeDir = home('unmanaged-listener');
  const server = net.createServer();
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const { port } = server.address();
  let state;
  try {
    await assert.rejects(async () => {
      state = await processApi.startProcess({
        config: { host: '127.0.0.1', port },
        runtime: {
          command: process.execPath,
          args: ['-e', 'setInterval(() => {}, 1000)'],
          env: process.env,
          python: false,
        },
        homeDir,
      });
    }, /port.*already in use|already.*port/i);
  } finally {
    if (state) await processApi.stopProcess({ homeDir });
    await new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
    fs.rmSync(homeDir, { recursive: true, force: true });
  }
});

test('start rejects a child that exits during the startup grace period', async () => {
  const homeDir = home('startup-exit');
  try {
    await assert.rejects(() => processApi.startProcess({
      config: { host: '127.0.0.1', port: 18876 },
      runtime: {
        command: process.execPath,
        args: ['-e', 'setTimeout(() => process.exit(23), 700)'],
        env: process.env,
        python: false,
      },
      homeDir,
    }), /exited during startup/i);
    assert.equal(fs.existsSync(processApi.statePath(homeDir)), false);
  } finally {
    await processApi.stopProcess({ homeDir });
    fs.rmSync(homeDir, { recursive: true, force: true });
  }
});

test('lifecycle starts a managed child and removes its state on stop', async () => {
  const homeDir = home('start-stop');
  const runtime = {
    command: process.execPath,
    args: ['-e', 'setInterval(() => {}, 1000)'],
    env: process.env,
    python: false,
  };
  const state = await processApi.startProcess({
    config: { host: '127.0.0.1', port: 8878 },
    runtime,
    homeDir,
  });
  assert.equal(Number.isInteger(state.pid), true);
  assert.equal(typeof state.identity.startMarker, 'string');
  assert.equal(typeof state.identity.executable, 'string');
  assert.equal(processApi.readStatus({ homeDir }).running, true);
  await processApi.stopProcess({ homeDir });
  assert.equal(processApi.readStatus({ homeDir }).running, false);
  assert.equal(fs.existsSync(processApi.statePath(homeDir)), false);
  fs.rmSync(homeDir, { recursive: true, force: true });
});

test('lifecycle refuses to kill a live process when recorded ownership does not match', async () => {
  const homeDir = home('ownership-mismatch');
  const unrelated = spawn(process.execPath, ['-e', 'setInterval(() => {}, 1000)'], {
    detached: false,
    stdio: 'ignore',
  });
  await once(unrelated, 'spawn');
  try {
    fs.mkdirSync(path.join(homeDir, '.media-bridge'), { recursive: true });
    fs.writeFileSync(processApi.statePath(homeDir), JSON.stringify({
      pid: unrelated.pid,
      command: process.execPath,
      identity: { executable: process.execPath, startMarker: 'not-the-current-process' },
    }));
    const result = await processApi.stopProcess({ homeDir });
    assert.equal(result.ownershipMismatch, true);
    assert.equal(processApi.isAlive(unrelated.pid), true);
    assert.equal(fs.existsSync(processApi.statePath(homeDir)), false);
  } finally {
    if (processApi.isAlive(unrelated.pid)) unrelated.kill();
    fs.rmSync(homeDir, { recursive: true, force: true });
  }
});

for (const platform of ['win32', 'linux']) {
  test(`stop refuses a mismatched ${platform} process without invoking kill`, async () => {
    const homeDir = home(`synthetic-stop-${platform}`);
    const pid = platform === 'win32' ? 41001 : 41002;
    fs.mkdirSync(path.join(homeDir, '.media-bridge'), { recursive: true });
    fs.writeFileSync(processApi.statePath(homeDir), JSON.stringify({
      pid,
      command: platform === 'win32' ? 'C:\\Runtime\\python.exe' : '/opt/runtime/bin/python',
      identity: {
        executable: platform === 'win32' ? 'C:\\Runtime\\python.exe' : '/opt/runtime/bin/python',
        startMarker: `${platform}:recorded-start`,
      },
    }));
    let killCalls = 0;
    const result = await processApi.stopProcess({
      homeDir,
      platform,
      isAliveImpl: () => true,
      inspectIdentity: () => ({
        executable: platform === 'win32' ? 'C:\\Runtime\\python.exe' : '/opt/runtime/bin/python',
        startMarker: `${platform}:different-start`,
      }),
      killImpl: () => { killCalls += 1; },
    });
    assert.equal(result.ownershipMismatch, true);
    assert.equal(killCalls, 0);
    assert.equal(fs.existsSync(processApi.statePath(homeDir)), false);
    fs.rmSync(homeDir, { recursive: true, force: true });
  });

  test(`status rejects a mismatched ${platform} process and removes its state`, () => {
    const homeDir = home(`synthetic-status-${platform}`);
    const pid = platform === 'win32' ? 42001 : 42002;
    fs.mkdirSync(path.join(homeDir, '.media-bridge'), { recursive: true });
    fs.writeFileSync(processApi.statePath(homeDir), JSON.stringify({
      pid,
      command: platform === 'win32' ? 'C:\\Runtime\\python.exe' : '/opt/runtime/bin/python',
      identity: {
        executable: platform === 'win32' ? 'C:\\Runtime\\python.exe' : '/opt/runtime/bin/python',
        startMarker: `${platform}:recorded-start`,
      },
    }));
    const result = processApi.readStatus({
      homeDir,
      platform,
      isAliveImpl: () => true,
      inspectIdentity: () => ({
        executable: platform === 'win32' ? 'C:\\Runtime\\python.exe' : '/opt/runtime/bin/python',
        startMarker: `${platform}:different-start`,
      }),
    });
    assert.deepEqual(result, { running: false, ownershipMismatch: true });
    assert.equal(fs.existsSync(processApi.statePath(homeDir)), false);
    fs.rmSync(homeDir, { recursive: true, force: true });
  });
}

test('lifecycle removes stale state without killing an unrelated process', async () => {
  const homeDir = home('stale');
  fs.mkdirSync(path.join(homeDir, '.media-bridge'), { recursive: true });
  fs.writeFileSync(processApi.statePath(homeDir), JSON.stringify({ pid: 999999, command: 'missing' }));
  const result = await processApi.stopProcess({ homeDir });
  assert.equal(result.running, false);
  assert.equal(fs.existsSync(processApi.statePath(homeDir)), false);
  fs.rmSync(homeDir, { recursive: true, force: true });
});

test('health returns stable JSON for success and network failure', async () => {
  const healthy = await processApi.checkHealth({
    config: { host: '127.0.0.1', port: 8878 },
    fetchImpl: async () => ({ ok: true, status: 200 }),
  });
  assert.deepEqual(healthy, { healthy: true, status: 200, url: 'http://127.0.0.1:8878/health' });
  const failed = await processApi.checkHealth({
    config: { host: '127.0.0.1', port: 8878 },
    fetchImpl: async () => { throw new Error('offline'); },
  });
  assert.deepEqual(failed, { healthy: false, status: null, url: 'http://127.0.0.1:8878/health' });
});

test('lifecycle provisions the required packaged-runtime environment from mb config', () => {
  const homeDir = home('runtime-environment');
  const config = {
    host: '127.0.0.1',
    port: 8878,
    solar: {
      model: 'solar-pro4',
      endpoint: 'https://api.upstage.ai/v1/chat/completions',
      apiKeyEnv: 'CUSTOM_SOLAR_KEY',
    },
    ocr: {
      endpoint: 'https://api.upstage.ai/v1/document-digitization',
      model: 'document-parse',
      apiKeyEnv: 'CUSTOM_SOLAR_KEY',
    },
    conversion: {
      maxBytes: 4194304,
      ocrEnabled: true,
      visionEnabled: false,
    },
    failurePolicy: {
      blockSolarOnPreparationFailure: true,
    },
  };
  const runtimeEnv = processApi.prepareRuntimeEnvironment({
    config,
    homeDir,
    env: { CUSTOM_SOLAR_KEY: 'not-written-to-disk' },
  });

  assert.equal(path.isAbsolute(runtimeEnv.MEDIA_BRIDGE_MODEL_REGISTRY), true);
  assert.equal(path.isAbsolute(runtimeEnv.MEDIA_BRIDGE_ASSET_ROOT), true);
  assert.equal(fs.existsSync(runtimeEnv.MEDIA_BRIDGE_MODEL_REGISTRY), true);
  assert.equal(fs.existsSync(runtimeEnv.MEDIA_BRIDGE_ASSET_ROOT), true);
  assert.match(fs.readFileSync(runtimeEnv.MEDIA_BRIDGE_MODEL_REGISTRY, 'utf8'), /solar-pro4/);
  assert.equal(fs.existsSync(runtimeEnv.MEDIA_BRIDGE_RECEIPT_SECRET_FILE), true);
  assert.equal(fs.existsSync(runtimeEnv.MEDIA_BRIDGE_SERVICE_TOKEN_FILE), true);
  assert.equal(runtimeEnv.MEDIA_BRIDGE_RECEIPT_SECRET, undefined);
  assert.equal(runtimeEnv.MEDIA_BRIDGE_SERVICE_TOKEN, undefined);
  assert.equal(runtimeEnv.MEDIA_BRIDGE_SOLAR_ENDPOINT, config.solar.endpoint);
  assert.equal(runtimeEnv.MEDIA_BRIDGE_SOLAR_MODEL, config.solar.model);
  assert.equal(runtimeEnv.MEDIA_BRIDGE_RUNTIME_MODE, 'personal');
  assert.equal(
    runtimeEnv.MEDIA_BRIDGE_CREDENTIAL_STORE_FILE,
    path.join(homeDir, '.media-bridge', 'secrets', 'providers.json'),
  );
  assert.equal(runtimeEnv.MEDIA_BRIDGE_TEXT_LLM_PROTOCOL, 'openai-chat-completions');
  assert.equal(runtimeEnv.MEDIA_BRIDGE_TEXT_LLM_CREDENTIAL_REF, 'text-llm');
  assert.equal(runtimeEnv.MEDIA_BRIDGE_MEDIA_PROCESSOR_PROTOCOL, 'upstage-document-parse');
  assert.equal(runtimeEnv.MEDIA_BRIDGE_MEDIA_PROCESSOR_CREDENTIAL_REF, 'media-processor');
  assert.equal(runtimeEnv.MEDIA_BRIDGE_OCR_ENDPOINT, config.ocr.endpoint);
  assert.equal(runtimeEnv.MEDIA_BRIDGE_OCR_CREDENTIAL_ENV, 'CUSTOM_SOLAR_KEY');
  assert.equal(runtimeEnv.MEDIA_BRIDGE_SOLAR_CREDENTIAL_ENV, 'CUSTOM_SOLAR_KEY');
  assert.equal(runtimeEnv.MEDIA_BRIDGE_MAX_REQUEST_BYTES, '4194304');
  assert.equal(runtimeEnv.MEDIA_BRIDGE_OCR_ENABLED, 'true');
  assert.equal(runtimeEnv.MEDIA_BRIDGE_VISION_ENABLED, 'false');
  assert.equal(runtimeEnv.MEDIA_BRIDGE_BLOCK_SOLAR_ON_FAILURE, 'true');
  assert.equal(runtimeEnv.MEDIA_BRIDGE_CONFIG_FILE, path.join(homeDir, '.media-bridge', 'config.json'));
  assert.equal(runtimeEnv.MEDIA_BRIDGE_VISION_ENDPOINT, undefined);
  assert.equal(runtimeEnv.MEDIA_BRIDGE_VISION_MODEL, undefined);
  assert.equal(runtimeEnv.SOLAR_API_KEY, 'not-written-to-disk');
  assert.equal(runtimeEnv.MEDIA_BRIDGE_VISION_API_KEY, 'not-written-to-disk');
  assert.equal(runtimeEnv.UPSTAGE_API_KEY, 'not-written-to-disk');
  assert.doesNotMatch(
    fs.readFileSync(runtimeEnv.MEDIA_BRIDGE_MODEL_REGISTRY, 'utf8'),
    /not-written-to-disk/,
  );
  fs.rmSync(homeDir, { recursive: true, force: true });
});

test('stop waits for an owned process to exit after sending the termination signal', async () => {
  const homeDir = home('wait-for-exit');
  const pid = 43001;
  fs.mkdirSync(path.join(homeDir, '.media-bridge'), { recursive: true });
  fs.writeFileSync(processApi.statePath(homeDir), JSON.stringify({
    pid,
    command: 'C:\\Runtime\\media-bridge-runtime.exe',
    identity: {
      executable: 'C:\\Runtime\\media-bridge-runtime.exe',
      startMarker: 'win32:owned-start',
    },
  }));
  let killed = false;
  let postKillChecks = 0;
  const result = await processApi.stopProcess({
    homeDir,
    platform: 'win32',
    isAliveImpl: () => {
      if (!killed) return true;
      postKillChecks += 1;
      return postKillChecks < 3;
    },
    inspectIdentity: () => ({
      executable: 'C:\\Runtime\\media-bridge-runtime.exe',
      startMarker: 'win32:owned-start',
    }),
    killImpl: () => { killed = true; },
    sleepImpl: async () => {},
  });
  assert.equal(killed, true);
  assert.ok(postKillChecks >= 3);
  assert.equal(result.running, false);
  assert.equal(fs.existsSync(processApi.statePath(homeDir)), false);
  fs.rmSync(homeDir, { recursive: true, force: true });
});

test('managed runtime removal retries transient Windows lock errors', async () => {
  let attempts = 0;
  let observed;
  await processApi.removeManagedTree('C:\\isolated\\runtime', {
    rmImpl: async (target, options) => {
      attempts += 1;
      observed = { target, options };
      if (attempts < 3) {
        const error = new Error('temporarily locked');
        error.code = 'EPERM';
        throw error;
      }
    },
    sleepImpl: async () => {},
  });
  assert.equal(attempts, 3);
  assert.equal(observed.target, 'C:\\isolated\\runtime');
  assert.deepEqual(observed.options, { recursive: true, force: true });
});

test('start passes the provisioned environment to the packaged runtime process', async () => {
  const homeDir = home('runtime-child-environment');
  const capturedPath = path.join(homeDir, 'child-environment.json');
  const captureScript = [
    `require('node:fs').writeFileSync(${JSON.stringify(capturedPath)}, JSON.stringify({`,
    'registry: process.env.MEDIA_BRIDGE_MODEL_REGISTRY,',
    'assets: process.env.MEDIA_BRIDGE_ASSET_ROOT,',
    'receiptFile: process.env.MEDIA_BRIDGE_RECEIPT_SECRET_FILE,',
    'runtimeMode: process.env.MEDIA_BRIDGE_RUNTIME_MODE,',
    'serviceTokenFile: process.env.MEDIA_BRIDGE_SERVICE_TOKEN_FILE,',
    'ocrEndpoint: process.env.MEDIA_BRIDGE_OCR_ENDPOINT,',
    'ocrCredentialEnv: process.env.MEDIA_BRIDGE_OCR_CREDENTIAL_ENV,',
    'solarCredentialEnv: process.env.MEDIA_BRIDGE_SOLAR_CREDENTIAL_ENV,',
    'solarEndpoint: process.env.MEDIA_BRIDGE_SOLAR_ENDPOINT,',
    'solarModel: process.env.MEDIA_BRIDGE_SOLAR_MODEL,',
    '})); setInterval(() => {}, 1000);',
  ].join('');
  const runtime = {
    command: process.execPath,
    args: ['-e', captureScript],
    env: {},
    python: false,
  };
  try {
    await processApi.startProcess({
      config: {
        host: '127.0.0.1',
        port: 8878,
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
      },
      runtime,
      homeDir,
    });
    const deadline = Date.now() + 2000;
    while (!fs.existsSync(capturedPath) && Date.now() < deadline) {
      await new Promise((resolve) => setTimeout(resolve, 25));
    }
    const captured = JSON.parse(fs.readFileSync(capturedPath, 'utf8'));
    assert.deepEqual(Object.keys(captured).sort(), [
      'assets', 'ocrCredentialEnv', 'ocrEndpoint', 'receiptFile', 'registry', 'runtimeMode',
      'serviceTokenFile', 'solarCredentialEnv', 'solarEndpoint', 'solarModel',
    ]);
    for (const value of Object.values(captured)) assert.equal(typeof value, 'string');
  } finally {
    await processApi.stopProcess({ homeDir });
    fs.rmSync(homeDir, { recursive: true, force: true });
  }
});

test('python QA fallback selects the personal npm runtime entrypoint', () => {
  assert.deepEqual(processApi.buildRuntimeArgs({ args: ['-I'], python: true }), [
    '-I',
    '-c',
    'from media_bridge_personal.npm_runtime import run_personal_npm_runtime; run_personal_npm_runtime()',
  ]);
});
