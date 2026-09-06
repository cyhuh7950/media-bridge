const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const root = path.resolve(__dirname, '../..');

test('0.1.12 release metadata stays aligned across npm and native runtime workflows', () => {
  const packageMetadata = JSON.parse(fs.readFileSync(
    path.join(root, 'packaging', 'npm', 'package.json'),
    'utf8',
  ));
  const manifest = JSON.parse(fs.readFileSync(
    path.join(root, 'packaging', 'npm', 'runtime-manifest.json'),
    'utf8',
  ));

  assert.equal(packageMetadata.name, '@cyhuh/media-bridge');
  assert.equal(packageMetadata.version, '0.1.12');
  assert.equal(manifest.packageVersion, '0.1.12');
  for (const platform of ['linux-arm64', 'linux-x64', 'win32-x64']) {
    const artifact = manifest.artifacts[platform];
    assert.equal(artifact.version, '0.1.12');
    assert.match(artifact.url, /\/v0\.1\.12\/media-bridge-runtime-0\.1\.12-/);
  }

  for (const workflowName of [
    'build-runtime-linux-arm64.yml',
    'build-runtime-linux-x64.yml',
    'build-runtime-win32-x64.yml',
  ]) {
    const workflow = fs.readFileSync(path.join(root, '.github', 'workflows', workflowName), 'utf8');
    assert.match(workflow, /default:\s*0\.1\.12/);
  }

  const releaseWorkflow = fs.readFileSync(
    path.join(root, '.github', 'workflows', 'publish-npm-runtime-release.yml'),
    'utf8',
  );
  assert.match(releaseWorkflow, /VERSION:\s*0\.1\.12/);
  assert.match(releaseWorkflow, /TAG:\s*v0\.1\.12/);
  assert.match(releaseWorkflow, /SOURCE_COMMIT:\s*f554ea9ae24e8363c4816eca4ec67b0b92ed1734/);
  assert.match(releaseWorkflow, /publish-npm-package:/);
  assert.match(releaseWorkflow, /id-token:\s*write/);
});
