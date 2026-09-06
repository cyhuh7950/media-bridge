const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const test = require('node:test');

const root = path.resolve(__dirname, '../..');
const packageRoot = path.join(root, 'packaging', 'npm');
const buildScript = path.join(root, 'packaging', 'runtime', 'build-linux-x64.sh');
const verifyScript = path.join(root, 'packaging', 'runtime', 'verify-linux-x64.sh');
const arm64BuildScript = path.join(root, 'packaging', 'runtime', 'build-linux-arm64.sh');
const arm64VerifyScript = path.join(root, 'packaging', 'runtime', 'verify-linux-arm64.sh');
const { loadRuntimeManifest, selectArtifact } = require('../../packaging/npm/lib/runtime.cjs');

test('published package selects the exact linux-x64 v0.1.12 runtime', () => {
  const packageMetadata = JSON.parse(fs.readFileSync(path.join(packageRoot, 'package.json'), 'utf8'));
  const manifest = loadRuntimeManifest({
    manifestPath: path.join(packageRoot, 'runtime-manifest.json'),
    packageVersion: packageMetadata.version,
  });
  const artifact = selectArtifact({
    manifest,
    packageVersion: packageMetadata.version,
    platform: 'linux',
    arch: 'x64',
  });

  assert.equal(packageMetadata.name, '@cyhuh/media-bridge');
  assert.equal(packageMetadata.version, '0.1.12');
  assert.deepEqual(
    {
      key: artifact.key,
      version: artifact.version,
      published: artifact.published,
      url: artifact.url,
      archive: artifact.archive,
      command: artifact.command,
      python: artifact.python,
    },
    {
      key: 'linux-x64',
      version: '0.1.12',
      published: true,
      url: 'https://github.com/cyhuh7950/media-bridge/releases/download/v0.1.12/media-bridge-runtime-0.1.12-linux-x64.tar.gz',
      archive: 'tar.gz',
      command: 'bin/media-bridge-runtime',
      python: false,
    },
  );
  assert.equal(artifact.sha256, '359209b05563c188168e1d26251b6b0cbde91160a9529076638f4b6bc5d42c3b');
});

test('published package selects the exact win32-x64 v0.1.12 runtime', () => {
  const packageMetadata = JSON.parse(fs.readFileSync(path.join(packageRoot, 'package.json'), 'utf8'));
  const manifest = loadRuntimeManifest({
    manifestPath: path.join(packageRoot, 'runtime-manifest.json'),
    packageVersion: packageMetadata.version,
  });
  const artifact = selectArtifact({
    manifest,
    packageVersion: packageMetadata.version,
    platform: 'win32',
    arch: 'x64',
  });

  assert.deepEqual(
    {
      key: artifact.key,
      version: artifact.version,
      published: artifact.published,
      url: artifact.url,
      archive: artifact.archive,
      command: artifact.command,
      python: artifact.python,
    },
    {
      key: 'win32-x64',
      version: '0.1.12',
      published: true,
      url: 'https://github.com/cyhuh7950/media-bridge/releases/download/v0.1.12/media-bridge-runtime-0.1.12-win32-x64.tar.gz',
      archive: 'tar.gz',
      command: 'bin/media-bridge-runtime.exe',
      python: false,
    },
  );
  assert.equal(artifact.sha256, '396cc637c9738c2be89623a032a8559430ad5152b58468daea62488eeb3fc2b0');
});

test('published package selects the exact linux-arm64 v0.1.12 runtime', () => {
  const packageMetadata = JSON.parse(fs.readFileSync(path.join(packageRoot, 'package.json'), 'utf8'));
  const manifest = loadRuntimeManifest({
    manifestPath: path.join(packageRoot, 'runtime-manifest.json'),
    packageVersion: packageMetadata.version,
  });
  const artifact = selectArtifact({
    manifest,
    packageVersion: packageMetadata.version,
    platform: 'linux',
    arch: 'arm64',
  });

  assert.deepEqual(
    {
      key: artifact.key,
      version: artifact.version,
      published: artifact.published,
      url: artifact.url,
      archive: artifact.archive,
      command: artifact.command,
      python: artifact.python,
    },
    {
      key: 'linux-arm64',
      version: '0.1.12',
      published: true,
      url: 'https://github.com/cyhuh7950/media-bridge/releases/download/v0.1.12/media-bridge-runtime-0.1.12-linux-arm64.tar.gz',
      archive: 'tar.gz',
      command: 'bin/media-bridge-runtime',
      python: false,
    },
  );
  assert.equal(artifact.sha256, 'a9cdedb2c600de74d285af4ce4a5607f02fbfce7b5425cfbc44f94bbcb1ce059');
});

test('linux-arm64 workflow builds and verifies the v0.1.12 candidate on the native ARM64 runner', () => {
  const workflow = fs.readFileSync(
    path.join(root, '.github', 'workflows', 'build-runtime-linux-arm64.yml'),
    'utf8',
  );

  assert.match(workflow, /default:\s*0\.1\.12/);
  assert.match(workflow, /runs-on:\s*ubuntu-24\.04-arm/);
  assert.match(workflow, /packaging\/runtime\/build-linux-arm64\.sh/);
  assert.match(workflow, /packaging\/runtime\/verify-linux-arm64\.sh/);
});

test('native runtime workflows support SSH-triggered release tags', () => {
  for (const name of [
    'build-runtime-linux-arm64.yml',
    'build-runtime-linux-x64.yml',
    'build-runtime-win32-x64.yml',
  ]) {
    const workflow = fs.readFileSync(path.join(root, '.github', 'workflows', name), 'utf8');
    assert.match(workflow, /push:\s*\n\s*tags:\s*\n\s*- ['"]runtime-v\*['"]/);
    assert.match(workflow, /GITHUB_REF_NAME/);
    assert.match(workflow, /RUNTIME_VERSION/);
  }
});

test('linux-arm64 runtime build rejects an invalid version before creating output', {
  skip: process.platform !== 'linux',
}, () => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'mb-linux-arm64-build-contract-'));
  const output = path.join(tempRoot, 'output');
  const work = path.join(tempRoot, 'work');
  try {
    const result = spawnSync('bash', [
      arm64BuildScript,
      '--python', '/missing/python3',
      '--version', 'latest',
      '--output-dir', output,
      '--work-dir', work,
      '--base-url', 'http://127.0.0.1:18080',
    ], { encoding: 'utf8' });

    assert.notEqual(result.status, 0);
    assert.match(`${result.stdout}\n${result.stderr}`, /Version must use x\.y\.z/);
    assert.equal(fs.existsSync(output), false);
    assert.equal(fs.existsSync(work), false);
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
});

test('linux-arm64 runtime verifier rejects a relative artifact directory', {
  skip: process.platform !== 'linux',
}, () => {
  const result = spawnSync('bash', [
    arm64VerifyScript,
    '--artifact-dir', 'relative-output',
    '--test-root', '/tmp/media-bridge-arm64-relative-verifier-test',
    '--source-commit', 'abcdef0',
  ], { encoding: 'utf8' });

  assert.notEqual(result.status, 0);
  assert.match(`${result.stdout}\n${result.stderr}`, /ArtifactDirectory must be an absolute path/);
});

test('linux runtime build rejects an invalid version before creating output', {
  skip: process.platform !== 'linux',
}, () => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'mb-linux-build-contract-'));
  const output = path.join(tempRoot, 'output');
  const work = path.join(tempRoot, 'work');
  try {
    const result = spawnSync('bash', [
      buildScript,
      '--python', '/missing/python3',
      '--version', 'latest',
      '--output-dir', output,
      '--work-dir', work,
      '--base-url', 'http://127.0.0.1:18080',
    ], { encoding: 'utf8' });

    assert.notEqual(result.status, 0);
    assert.match(`${result.stdout}\n${result.stderr}`, /Version must use x\.y\.z/);
    assert.equal(fs.existsSync(output), false);
    assert.equal(fs.existsSync(work), false);
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
});

test('linux runtime verifier rejects a relative artifact directory', {
  skip: process.platform !== 'linux',
}, () => {
  const result = spawnSync('bash', [
    verifyScript,
    '--artifact-dir', 'relative-output',
    '--test-root', '/tmp/media-bridge-relative-verifier-test',
    '--source-commit', 'abcdef0',
  ], { encoding: 'utf8' });

  assert.notEqual(result.status, 0);
  assert.match(`${result.stdout}\n${result.stderr}`, /ArtifactDirectory must be an absolute path/);
});
