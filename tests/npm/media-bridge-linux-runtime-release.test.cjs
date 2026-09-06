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

test('published package selects the exact linux-x64 v0.1.13 runtime', () => {
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
  assert.equal(packageMetadata.version, '0.1.13');
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
      version: '0.1.13',
      published: true,
      url: 'https://github.com/cyhuh7950/media-bridge/releases/download/v0.1.13/media-bridge-runtime-0.1.13-linux-x64.tar.gz',
      archive: 'tar.gz',
      command: 'bin/media-bridge-runtime',
      python: false,
    },
  );
  assert.equal(artifact.sha256, 'f82449d487dc7287f07f1a4a7342ee389e9ad61bc6b315c0e00aac65a7e2964b');
});

test('published package selects the exact win32-x64 v0.1.13 runtime', () => {
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
      version: '0.1.13',
      published: true,
      url: 'https://github.com/cyhuh7950/media-bridge/releases/download/v0.1.13/media-bridge-runtime-0.1.13-win32-x64.tar.gz',
      archive: 'tar.gz',
      command: 'bin/media-bridge-runtime.exe',
      python: false,
    },
  );
  assert.equal(artifact.sha256, '3801cef1a8df3a1f1fe98d767980f5fd7d4abe8a9b19bdbc3db9d15705d12879');
});

test('published package selects the exact linux-arm64 v0.1.13 runtime', () => {
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
      version: '0.1.13',
      published: true,
      url: 'https://github.com/cyhuh7950/media-bridge/releases/download/v0.1.13/media-bridge-runtime-0.1.13-linux-arm64.tar.gz',
      archive: 'tar.gz',
      command: 'bin/media-bridge-runtime',
      python: false,
    },
  );
  assert.equal(artifact.sha256, '06d36d38e0490d31801f1c7bd306e438e0110118f26d6197783e818d8d9f7710');
});

test('linux-arm64 workflow builds and verifies the v0.1.13 candidate on the native ARM64 runner', () => {
  const workflow = fs.readFileSync(
    path.join(root, '.github', 'workflows', 'build-runtime-linux-arm64.yml'),
    'utf8',
  );

  assert.match(workflow, /default:\s*0\.1\.13/);
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
