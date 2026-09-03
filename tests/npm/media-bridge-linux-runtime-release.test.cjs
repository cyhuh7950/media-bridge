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
const { loadRuntimeManifest, selectArtifact } = require('../../packaging/npm/lib/runtime.cjs');

test('published package selects the exact linux-x64 v0.1.4 runtime', () => {
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
  assert.equal(packageMetadata.version, '0.1.4');
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
      version: '0.1.4',
      published: true,
      url: 'https://github.com/cyhuh7950/media-bridge/releases/download/v0.1.4/media-bridge-runtime-0.1.4-linux-x64.tar.gz',
      archive: 'tar.gz',
      command: 'bin/media-bridge-runtime',
      python: false,
    },
  );
  assert.match(artifact.sha256, /^[a-f0-9]{64}$/);
});

test('published package selects the exact win32-x64 v0.1.4 runtime', () => {
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
      version: '0.1.4',
      published: true,
      url: 'https://github.com/cyhuh7950/media-bridge/releases/download/v0.1.4/media-bridge-runtime-0.1.4-win32-x64.tar.gz',
      archive: 'tar.gz',
      command: 'bin/media-bridge-runtime.exe',
      python: false,
    },
  );
  assert.match(artifact.sha256, /^[a-f0-9]{64}$/);
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
