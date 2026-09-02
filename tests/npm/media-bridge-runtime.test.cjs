const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
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
    packageVersion: '0.1.0',
    artifacts: {
      'win32-x64': {
        version: '0.1.0',
        published: true,
        url: 'http://127.0.0.1:18080/media-bridge-runtime-0.1.0-win32-x64.tar.gz',
        sha256: 'a'.repeat(64),
        archive: 'tar.gz',
        command: 'bin/media-bridge-runtime.exe',
        python: false,
        ...overrides,
      },
    },
  };
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

test('manifest selects the exact published win32-x64 artifact', () => {
  assert.deepEqual(selectArtifact({
    manifest: publishedManifest(),
    packageVersion: '0.1.0',
    platform: 'win32',
    arch: 'x64',
  }), {
    key: 'win32-x64',
    version: '0.1.0',
    published: true,
    url: 'http://127.0.0.1:18080/media-bridge-runtime-0.1.0-win32-x64.tar.gz',
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
  assert.throws(() => loadRuntimeManifest({ manifestPath, packageVersion: '0.1.0' }), /schema/i);
  fs.writeFileSync(manifestPath, JSON.stringify({ ...publishedManifest(), packageVersion: '0.2.0' }));
  assert.throws(() => loadRuntimeManifest({ manifestPath, packageVersion: '0.1.0' }), /package.*version/i);
  fs.rmSync(tempRoot, { recursive: true, force: true });
});

test('manifest fails closed for unpublished, missing, or unsafe artifacts', () => {
  assert.throws(() => selectArtifact({
    manifest: publishedManifest({ published: false, url: null, sha256: null }),
    packageVersion: '0.1.0', platform: 'win32', arch: 'x64',
  }), /not published/i);
  assert.throws(() => selectArtifact({
    manifest: publishedManifest(), packageVersion: '0.1.0', platform: 'linux', arch: 'x64',
  }), /not available/i);
  assert.throws(() => selectArtifact({
    manifest: publishedManifest({ sha256: 'bad' }),
    packageVersion: '0.1.0', platform: 'win32', arch: 'x64',
  }), /sha-256/i);
  assert.throws(() => selectArtifact({
    manifest: publishedManifest({ command: '../escape.exe' }),
    packageVersion: '0.1.0', platform: 'win32', arch: 'x64',
  }), /command/i);
  assert.throws(() => selectArtifact({
    manifest: publishedManifest({ command: 'C:\\escape.exe' }),
    packageVersion: '0.1.0', platform: 'win32', arch: 'x64',
  }), /command/i);
  assert.throws(() => selectArtifact({
    manifest: publishedManifest({ archive: 'zip' }),
    packageVersion: '0.1.0', platform: 'win32', arch: 'x64',
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
});

test('runtime resolver fails closed when no managed artifact is available', async () => {
  const tempHome = path.join(testRoot, 'media-bridge-runtime-missing');
  fs.rmSync(tempHome, { recursive: true, force: true });
  await assert.rejects(() => resolveRuntime({
    homeDir: tempHome,
    env: {},
    platform: 'linux',
    arch: 'x64',
  }), /runtime.*(available|artifact)|artifact.*(available|configured)/i);
  assert.equal(fs.existsSync(runtimeDir(tempHome)), false);
});
