'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { once } = require('node:events');

const platforms = new Set(['linux-arm64', 'linux-x64', 'win32-x64']);

function createLoopbackManifest({ manifest, platform, url }) {
  if (!platforms.has(platform)) throw new Error('candidate platform is unsupported');
  let parsed;
  try { parsed = new URL(url); } catch { throw new Error('candidate runtime URL is invalid'); }
  if (parsed.protocol !== 'http:' || !['127.0.0.1', 'localhost', '[::1]'].includes(parsed.hostname)) {
    throw new Error('candidate runtime URL must use loopback HTTP');
  }
  if (parsed.username || parsed.password || parsed.search || parsed.hash) {
    throw new Error('candidate runtime URL must not contain credentials or query data');
  }
  const result = structuredClone(manifest);
  if (result.schemaVersion !== 1 || !result.artifacts?.[platform]) {
    throw new Error('candidate manifest does not contain the selected platform');
  }
  result.artifacts[platform].url = parsed.href;
  return result;
}

function parseArgs(args) {
  const result = {};
  for (let index = 0; index < args.length; index += 2) {
    const key = args[index];
    if (!key?.startsWith('--') || !args[index + 1]) throw new Error('expected --name value arguments');
    result[key.slice(2)] = args[index + 1];
  }
  for (const key of ['install-prefix', 'artifact-directory', 'test-root']) {
    if (!path.isAbsolute(result[key] || '')) throw new Error(`${key} must be an absolute path`);
  }
  return result;
}

function readJson(filePath, label) {
  try { return JSON.parse(fs.readFileSync(filePath, 'utf8')); } catch (error) {
    throw new Error(`${label} is missing or invalid: ${error.message}`);
  }
}

async function reserveLoopbackPort() {
  const server = http.createServer();
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  const port = server.address().port;
  await new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  return port;
}

async function waitForHealth(url, timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs;
  let lastError;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url, { signal: AbortSignal.timeout(2_000) });
      if (response.status === 200) return;
      lastError = new Error(`health returned HTTP ${response.status}`);
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`candidate runtime did not become healthy: ${lastError?.message || 'timeout'}`);
}

function postSameOriginJson(url, payload) {
  return fetch(url, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      origin: new URL(url).origin,
    },
    body: JSON.stringify(payload),
  });
}

async function runCandidateInstall({ installPrefix, artifactDirectory, testRoot }) {
  const tempBase = path.resolve(process.env.RUNNER_TEMP || os.tmpdir());
  for (const [label, target] of [['test-root', testRoot], ['install-prefix', installPrefix]]) {
    const relative = path.relative(tempBase, target);
    if (!relative || relative.startsWith('..') || path.isAbsolute(relative)) {
      throw new Error(`${label} must be a child of RUNNER_TEMP or the operating-system temp directory`);
    }
  }
  if (!path.basename(installPrefix).startsWith('candidate-npm-prefix-')) {
    throw new Error('install-prefix must use the candidate-npm-prefix- temporary name');
  }
  if (!fs.statSync(installPrefix, { throwIfNoEntry: false })?.isDirectory()) throw new Error('npm install prefix is missing');
  if (!fs.statSync(artifactDirectory, { throwIfNoEntry: false })?.isDirectory()) throw new Error('runtime artifact directory is missing');
  if (fs.existsSync(testRoot)) throw new Error('test-root must not already exist');
  fs.mkdirSync(testRoot, { recursive: false });

  let server;
  let homeDir;
  let started = false;
  try {
    const packageDirectory = path.join(installPrefix, 'node_modules', '@cyhuh', 'media-bridge');
    const packageMetadata = readJson(path.join(packageDirectory, 'package.json'), 'installed npm metadata');
    const manifest = readJson(path.join(packageDirectory, 'runtime-manifest.json'), 'installed candidate manifest');
    if (packageMetadata.name !== '@cyhuh/media-bridge' || packageMetadata.version !== '0.1.14'
        || manifest.packageVersion !== packageMetadata.version) {
      throw new Error('installed npm package and runtime manifest versions do not match candidate 0.1.14');
    }
    const platformKey = `${process.platform}-${process.arch}`;
    if (!platforms.has(platformKey)) throw new Error(`native runner platform is unsupported: ${platformKey}`);
    const entry = manifest.artifacts?.[platformKey];
    if (!entry) throw new Error(`candidate manifest does not contain ${platformKey}`);
    const artifactName = `media-bridge-runtime-${packageMetadata.version}-${platformKey}.tar.gz`;
    const artifactPath = path.join(artifactDirectory, artifactName);
    if (!fs.statSync(artifactPath, { throwIfNoEntry: false })?.isFile()) {
      throw new Error(`native runtime artifact is missing: ${artifactName}`);
    }
    const evidence = readJson(path.join(artifactDirectory, `verification-result-${platformKey}.json`), 'native verification evidence');
    const sourceEvidence = readJson(path.join(path.dirname(artifactDirectory), 'candidate-evidence.json'), 'candidate source evidence');
    const platformEvidence = sourceEvidence.platforms?.[platformKey];
    const digest = require('node:crypto').createHash('sha256').update(fs.readFileSync(artifactPath)).digest('hex');
    if (evidence.sha256 !== digest || evidence.healthStatus !== 200
        || evidence.packageVersion !== packageMetadata.version || evidence.runtimeVersion !== packageMetadata.version
        || evidence.platform !== platformKey || evidence.artifactName !== artifactName
        || sourceEvidence.version !== packageMetadata.version || sourceEvidence.sourceCommit !== evidence.sourceCommit
        || !/^[a-f0-9]{40}$/i.test(evidence.sourceCommit || '')
        || platformEvidence?.artifactName !== artifactName || platformEvidence?.sha256 !== digest
        || platformEvidence?.healthStatus !== 200
        || entry.sha256 !== digest) {
      throw new Error('native runtime artifact does not match the candidate verification evidence');
    }

    server = http.createServer((request, response) => {
      if (request.method !== 'GET' || request.url !== `/${artifactName}`) {
        response.writeHead(404).end();
        return;
      }
      response.writeHead(200, { 'content-type': 'application/gzip' });
      fs.createReadStream(artifactPath).pipe(response);
    });
    server.listen(0, '127.0.0.1');
    await once(server, 'listening');
    const runtimeUrl = `http://127.0.0.1:${server.address().port}/${artifactName}`;
    const loopbackManifest = createLoopbackManifest({ manifest, platform: platformKey, url: runtimeUrl });
    const testManifestPath = path.join(testRoot, 'runtime-manifest.json');
    fs.writeFileSync(testManifestPath, `${JSON.stringify(loopbackManifest, null, 2)}\n`);

    const runtimeApi = require(path.join(packageDirectory, 'lib', 'runtime.cjs'));
    homeDir = path.join(testRoot, 'home');
    const runtimeEnv = {
      MEDIA_BRIDGE_RUNTIME_MANIFEST: testManifestPath,
      PATH: process.env.PATH || '',
      ...(process.platform === 'win32' ? {
        SystemRoot: process.env.SystemRoot || '',
        WINDIR: process.env.WINDIR || '',
        TEMP: process.env.TEMP || '',
        TMP: process.env.TMP || '',
      } : {}),
    };
    const runtime = await runtimeApi.resolveRuntime({
      homeDir,
      env: runtimeEnv,
      packageVersion: packageMetadata.version,
    });
    if (runtime.python !== false) throw new Error('installed package selected an unexpected Python runtime');
    await new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
    server = null;

    const packageConfig = require(path.join(packageDirectory, 'lib', 'config.cjs'));
    const processApi = require(path.join(packageDirectory, 'lib', 'process.cjs'));
    const port = await reserveLoopbackPort();
    const config = packageConfig.defaultConfig();
    config.port = port;
    config.opencodex.baseUrl = `http://127.0.0.1:${port}/v1`;
    config.codingAgent.baseUrl = config.opencodex.baseUrl;
    config.reasoningEffort = 'low';
    config.textLlm.reasoningEffort = 'provider_default';
    fs.mkdirSync(path.dirname(packageConfig.configPath(homeDir)), { recursive: true });
    fs.writeFileSync(packageConfig.configPath(homeDir), `${JSON.stringify(config, null, 2)}\n`);

    await processApi.startManagedRuntime({
      config,
      homeDir,
      portOverride: port,
      resolveRuntimeImpl: ({ homeDir: isolatedHome }) => runtimeApi.resolveRuntime({
        homeDir: isolatedHome,
        env: runtimeEnv,
        packageVersion: packageMetadata.version,
      }),
    });
    started = true;
    const baseUrl = `http://127.0.0.1:${port}`;
    await waitForHealth(`${baseUrl}/health`);
    const [pageResponse, initialSettingsResponse] = await Promise.all([
      fetch(`${baseUrl}/`),
      fetch(`${baseUrl}/api/settings`),
    ]);
    const html = await pageResponse.text();
    assert.equal(pageResponse.status, 200);
    assert.match(html, /name="media_bridge_reasoning_effort"/);
    assert.match(html, /name="reasoning_effort"/);
    assert.equal(initialSettingsResponse.status, 200);
    const initialSettings = await initialSettingsResponse.json();
    assert.equal(initialSettings.reasoningEffort, 'low');
    assert.equal(initialSettings.textLlm.reasoningEffort, 'provider_default');

    const update = {
      ...initialSettings,
      reasoningEffort: 'high',
      textLlm: { ...initialSettings.textLlm, reasoningEffort: 'low' },
    };
    const saveResponse = await postSameOriginJson(`${baseUrl}/api/settings`, update);
    assert.equal(saveResponse.status, 200);
    const savedSettings = await saveResponse.json();
    assert.equal(savedSettings.reasoningEffort, 'high');
    assert.equal(savedSettings.textLlm.reasoningEffort, 'low');
    const readBack = await (await fetch(`${baseUrl}/api/settings`)).json();
    assert.equal(readBack.reasoningEffort, 'high');
    assert.equal(readBack.textLlm.reasoningEffort, 'low');

    const cliHelp = execFileSync(process.execPath, [path.join(packageDirectory, 'bin', 'mb.cjs'), '--help'], {
      encoding: 'utf8',
      env: { ...runtimeEnv, HOME: homeDir, USERPROFILE: homeDir },
      windowsHide: true,
      timeout: 15_000,
    });
    assert.match(cliHelp, /Media Bridge/);
    return { platform: platformKey, packageVersion: packageMetadata.version, healthStatus: 200, settingsPersisted: true };
  } finally {
    if (started && homeDir) {
      try {
        const packageDirectory = path.join(installPrefix, 'node_modules', '@cyhuh', 'media-bridge');
        const processApi = require(path.join(packageDirectory, 'lib', 'process.cjs'));
        await processApi.stopProcess({ homeDir });
      } catch {}
    }
    if (server?.listening) {
      await new Promise((resolve) => server.close(() => resolve()));
    }
    fs.rmSync(testRoot, { recursive: true, force: true });
    fs.rmSync(installPrefix, { recursive: true, force: true });
  }
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const result = await runCandidateInstall({
    installPrefix: args['install-prefix'],
    artifactDirectory: args['artifact-directory'],
    testRoot: args['test-root'],
  });
  process.stdout.write(`${JSON.stringify(result)}\n`);
}

if (require.main === module) {
  main().catch((error) => {
    process.stderr.write(`${error.stack || error}\n`);
    process.exitCode = 1;
  });
}

module.exports = { createLoopbackManifest, postSameOriginJson, runCandidateInstall };
