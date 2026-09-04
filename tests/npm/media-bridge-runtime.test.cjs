const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');

const testRoot = process.env.MEDIA_BRIDGE_TEST_TMP || os.tmpdir();

const {
  loadRuntimeManifest,
  platformKey,
  resolveRuntime,
  runtimeDir,
  selectArtifact,
} = require('../../packaging/npm/lib/runtime.cjs');

function publishedManifest(overrides = {}) {
  return {
    schemaVersion: 1,
    packageVersion: '0.1.7',
    artifacts: {
      'win32-x64': {
        version: '0.1.7',
        published: true,
        url: 'http://127.0.0.1:18080/media-bridge-runtime-0.1.7-win32-x64.tar.gz',
        sha256: 'a'.repeat(64),
        archive: 'tar.gz',
        command: 'bin/media-bridge-runtime.exe',
        python: false,
        ...overrides,
      },
    },
  };
}

function createArtifact(root, { command = 'bin/media-bridge-runtime.exe', contents = 'runtime-v1' } = {}) {
  const payload = path.join(root, 'payload');
  const archive = path.join(root, 'runtime.tar.gz');
  fs.rmSync(payload, { recursive: true, force: true });
  fs.mkdirSync(path.dirname(path.join(payload, command)), { recursive: true });
  fs.writeFileSync(path.join(payload, command), contents);
  fs.chmodSync(path.join(payload, command), 0o755);
  const tarCommand = process.platform === 'win32'
    ? path.join(process.env.SystemRoot || 'C:\\Windows', 'System32', 'tar.exe')
    : 'tar';
  execFileSync(tarCommand, [
    '-czf', archive, '-C', payload, '.',
  ]);
  return {
    archive,
    bytes: fs.readFileSync(archive),
    sha256: crypto.createHash('sha256').update(fs.readFileSync(archive)).digest('hex'),
  };
}

test('runtime install succeeds when Git GNU tar precedes Windows system tar on PATH', {
  skip: process.platform !== 'win32',
}, async (context) => {
  const gitTarDirectory = 'C:\\Program Files\\Git\\usr\\bin';
  if (!fs.existsSync(path.join(gitTarDirectory, 'tar.exe'))) {
    context.skip('Git for Windows GNU tar is unavailable');
    return;
  }
  const root = path.join(testRoot, 'media-bridge-runtime-gnu-tar-path');
  fs.rmSync(root, { recursive: true, force: true });
  fs.mkdirSync(root, { recursive: true });
  const fixture = createArtifact(root);
  const server = await serveArtifact(fixture.bytes);
  const originalPath = process.env.Path;
  try {
    process.env.Path = `${gitTarDirectory};${originalPath || ''}`;
    const manifestPath = writeManifest(root, { url: server.url, sha256: fixture.sha256 });
    const result = await resolveRuntime({
      homeDir: path.join(root, 'home'),
      env: { MEDIA_BRIDGE_RUNTIME_MANIFEST: manifestPath },
      platform: 'win32',
      arch: 'x64',
    });
    assert.equal(fs.readFileSync(result.command, 'utf8'), 'runtime-v1');
  } finally {
    process.env.Path = originalPath;
    await server.close();
    fs.rmSync(root, { recursive: true, force: true });
  }
});

async function serveArtifact(bytes) {
  let requests = 0;
  const server = http.createServer((_request, response) => {
    requests += 1;
    response.writeHead(200, { 'content-type': 'application/gzip' });
    response.end(bytes);
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const address = server.address();
  return {
    url: `http://127.0.0.1:${address.port}/runtime.tar.gz`,
    requests: () => requests,
    close: () => new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve())),
  };
}

function writeManifest(root, artifact) {
  const manifestPath = path.join(root, 'runtime-manifest.json');
  fs.writeFileSync(manifestPath, JSON.stringify(publishedManifest(artifact)));
  return manifestPath;
}

test('runtime platform key supports the release target matrix', () => {
  assert.equal(platformKey('linux', 'x64'), 'linux-x64');
  assert.equal(platformKey('linux', 'arm64'), 'linux-arm64');
  assert.equal(platformKey('win32', 'x64'), 'win32-x64');
  assert.throws(() => platformKey('freebsd', 'x64'), /unsupported/i);
});

test('npm package includes the runtime support modules', () => {
  const packageJson = JSON.parse(fs.readFileSync(
    path.join(__dirname, '../../packaging/npm/package.json'),
    'utf8',
  ));
  assert.equal(packageJson.files.includes('lib'), true);
  assert.equal(packageJson.files.includes('runtime-manifest.json'), true);
  assert.equal(fs.existsSync(path.join(__dirname, '../../packaging/npm/runtime-manifest.json')), true);
});

test('win32 runtime build isolates PyInstaller from the caller working directory', () => {
  const buildScript = fs.readFileSync(
    path.join(__dirname, '../../packaging/runtime/build-win32-x64.ps1'),
    'utf8',
  );
  const pushLocation = buildScript.indexOf('Push-Location -LiteralPath $workPath');
  const pyInstaller = buildScript.indexOf('& $pythonPath -m PyInstaller');
  const popLocation = buildScript.indexOf('Pop-Location');

  assert.ok(pushLocation >= 0, 'build must enter its isolated work directory');
  assert.ok(pyInstaller > pushLocation, 'PyInstaller must run after entering the work directory');
  assert.ok(popLocation > pyInstaller, 'build must restore the caller working directory');

  const workflow = fs.readFileSync(
    path.join(__dirname, '../../.github/workflows/build-runtime-win32-x64.yml'),
    'utf8',
  );
  assert.match(workflow, /default:\s*0\.1\.7/);
});

test('manifest selects the exact published win32-x64 artifact', () => {
  assert.deepEqual(selectArtifact({
    manifest: publishedManifest(),
    packageVersion: '0.1.7',
    platform: 'win32',
    arch: 'x64',
  }), {
    key: 'win32-x64',
    version: '0.1.7',
    published: true,
    url: 'http://127.0.0.1:18080/media-bridge-runtime-0.1.7-win32-x64.tar.gz',
    sha256: 'a'.repeat(64),
    archive: 'tar.gz',
    command: 'bin/media-bridge-runtime.exe',
    python: false,
  });
});

test('manifest loader rejects schema and package version mismatches', () => {
  const tempRoot = path.join(testRoot, 'media-bridge-runtime-manifest-loader');
  fs.rmSync(tempRoot, { recursive: true, force: true });
  fs.mkdirSync(tempRoot, { recursive: true });
  const manifestPath = path.join(tempRoot, 'runtime-manifest.json');
  fs.writeFileSync(manifestPath, JSON.stringify({ ...publishedManifest(), schemaVersion: 2 }));
  assert.throws(() => loadRuntimeManifest({ manifestPath, packageVersion: '0.1.7' }), /schema/i);
  fs.writeFileSync(manifestPath, JSON.stringify({ ...publishedManifest(), packageVersion: '0.2.0' }));
  assert.throws(() => loadRuntimeManifest({ manifestPath, packageVersion: '0.1.7' }), /package.*version/i);
  fs.rmSync(tempRoot, { recursive: true, force: true });
});

test('manifest fails closed for unpublished, missing, or unsafe artifacts', () => {
  assert.throws(() => selectArtifact({
    manifest: publishedManifest({ published: false, url: null, sha256: null }),
    packageVersion: '0.1.7', platform: 'win32', arch: 'x64',
  }), /not published/i);
  assert.throws(() => selectArtifact({
    manifest: publishedManifest(), packageVersion: '0.1.7', platform: 'linux', arch: 'x64',
  }), /not available/i);
  assert.throws(() => selectArtifact({
    manifest: publishedManifest({ sha256: 'bad' }),
    packageVersion: '0.1.7', platform: 'win32', arch: 'x64',
  }), /sha-256/i);
  assert.throws(() => selectArtifact({
    manifest: publishedManifest({ command: '../escape.exe' }),
    packageVersion: '0.1.7', platform: 'win32', arch: 'x64',
  }), /command/i);
  assert.throws(() => selectArtifact({
    manifest: publishedManifest({ command: 'C:\\escape.exe' }),
    packageVersion: '0.1.7', platform: 'win32', arch: 'x64',
  }), /command/i);
  assert.throws(() => selectArtifact({
    manifest: publishedManifest({ archive: 'zip' }),
    packageVersion: '0.1.7', platform: 'win32', arch: 'x64',
  }), /archive/i);
});

test('runtime resolver honors an explicit local runtime command for QA', async () => {
  const result = await resolveRuntime({
    homeDir: path.join(testRoot, 'media-bridge-runtime-override'),
    env: { MEDIA_BRIDGE_RUNTIME_COMMAND: process.execPath },
    platform: 'win32',
    arch: 'x64',
  });
  assert.equal(result.command, process.execPath);
  assert.deepEqual(result.args, []);
  assert.equal(result.python, true);
});

test('runtime resolver can mark an explicit packaged binary as non-Python for QA', async () => {
  const result = await resolveRuntime({
    homeDir: path.join(testRoot, 'media-bridge-runtime-binary-override'),
    env: {
      MEDIA_BRIDGE_RUNTIME_COMMAND: 'C:\\qa\\media-bridge-runtime.exe',
      MEDIA_BRIDGE_RUNTIME_PYTHON: 'false',
    },
    platform: 'win32',
    arch: 'x64',
  });
  assert.equal(result.python, false);
});

test('runtime resolver fails closed when no managed artifact is available', async () => {
  const tempHome = path.join(testRoot, 'media-bridge-runtime-missing');
  const manifestRoot = path.join(testRoot, 'media-bridge-runtime-missing-manifest');
  fs.rmSync(tempHome, { recursive: true, force: true });
  fs.rmSync(manifestRoot, { recursive: true, force: true });
  fs.mkdirSync(manifestRoot, { recursive: true });
  const manifestPath = writeManifest(manifestRoot, {});
  await assert.rejects(() => resolveRuntime({
    homeDir: tempHome,
    env: { MEDIA_BRIDGE_RUNTIME_MANIFEST: manifestPath },
    platform: 'linux',
    arch: 'arm64',
  }), /runtime.*(available|artifact)|artifact.*(available|configured)/i);
  assert.equal(fs.existsSync(runtimeDir(tempHome)), false);
  fs.rmSync(manifestRoot, { recursive: true, force: true });
});

test('runtime resolver downloads the selected artifact and reuses verified metadata', async () => {
  const root = path.join(testRoot, 'media-bridge-runtime-download');
  fs.rmSync(root, { recursive: true, force: true });
  fs.mkdirSync(root, { recursive: true });
  const fixture = createArtifact(root);
  const server = await serveArtifact(fixture.bytes);
  try {
    const manifestPath = writeManifest(root, { url: server.url, sha256: fixture.sha256 });
    const env = { MEDIA_BRIDGE_RUNTIME_MANIFEST: manifestPath };
    const first = await resolveRuntime({ homeDir: path.join(root, 'home'), env, platform: 'win32', arch: 'x64' });
    assert.equal(first.command, path.join(root, 'home', '.media-bridge', 'runtime', 'bin', 'media-bridge-runtime.exe'));
    assert.equal(first.python, false);
    assert.equal(fs.readFileSync(first.command, 'utf8'), 'runtime-v1');
    assert.deepEqual(JSON.parse(fs.readFileSync(
      path.join(runtimeDir(path.join(root, 'home')), '.verified.json'), 'utf8',
    )), {
      schemaVersion: 1,
      platform: 'win32-x64',
      version: '0.1.7',
      sha256: fixture.sha256,
      command: 'bin/media-bridge-runtime.exe',
      python: false,
    });
    const second = await resolveRuntime({ homeDir: path.join(root, 'home'), env, platform: 'win32', arch: 'x64' });
    assert.equal(second.command, first.command);
    assert.equal(server.requests(), 1);
  } finally {
    await server.close();
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('checksum failure preserves the previous verified runtime', async () => {
  const root = path.join(testRoot, 'media-bridge-runtime-checksum-rollback');
  const homeDir = path.join(root, 'home');
  const installedRoot = runtimeDir(homeDir);
  fs.rmSync(root, { recursive: true, force: true });
  fs.mkdirSync(path.join(installedRoot, 'bin'), { recursive: true });
  fs.writeFileSync(path.join(installedRoot, 'bin', 'media-bridge-runtime.exe'), 'previous-runtime');
  fs.writeFileSync(path.join(installedRoot, '.verified.json'), JSON.stringify({
    schemaVersion: 1, platform: 'win32-x64', version: '0.0.9', sha256: 'b'.repeat(64),
    command: 'bin/media-bridge-runtime.exe', python: false,
  }));
  const fixture = createArtifact(root, { contents: 'replacement-runtime' });
  const server = await serveArtifact(fixture.bytes);
  try {
    const manifestPath = writeManifest(root, { url: server.url, sha256: 'c'.repeat(64) });
    await assert.rejects(() => resolveRuntime({
      homeDir, env: { MEDIA_BRIDGE_RUNTIME_MANIFEST: manifestPath }, platform: 'win32', arch: 'x64',
    }), /checksum mismatch/i);
    assert.equal(fs.readFileSync(path.join(installedRoot, 'bin', 'media-bridge-runtime.exe'), 'utf8'), 'previous-runtime');
  } finally {
    await server.close();
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('missing artifact command preserves the previous verified runtime', async () => {
  const root = path.join(testRoot, 'media-bridge-runtime-command-rollback');
  const homeDir = path.join(root, 'home');
  const installedRoot = runtimeDir(homeDir);
  fs.rmSync(root, { recursive: true, force: true });
  fs.mkdirSync(path.join(installedRoot, 'bin'), { recursive: true });
  fs.writeFileSync(path.join(installedRoot, 'bin', 'media-bridge-runtime.exe'), 'previous-runtime');
  const fixture = createArtifact(root, { command: 'bin/not-the-command.exe' });
  const server = await serveArtifact(fixture.bytes);
  try {
    const manifestPath = writeManifest(root, { url: server.url, sha256: fixture.sha256 });
    await assert.rejects(() => resolveRuntime({
      homeDir, env: { MEDIA_BRIDGE_RUNTIME_MANIFEST: manifestPath }, platform: 'win32', arch: 'x64',
    }), /command.*(missing|unavailable)/i);
    assert.equal(fs.readFileSync(path.join(installedRoot, 'bin', 'media-bridge-runtime.exe'), 'utf8'), 'previous-runtime');
  } finally {
    await server.close();
    fs.rmSync(root, { recursive: true, force: true });
  }
});
