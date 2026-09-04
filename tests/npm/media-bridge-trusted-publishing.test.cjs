const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const root = path.resolve(__dirname, '../..');
const workflowPath = path.join(root, '.github', 'workflows', 'publish-npm-runtime-release.yml');
const packagePath = path.join(root, 'packaging', 'npm', 'package.json');

test('release workflow publishes the npm package through GitHub OIDC without a long-lived token', () => {
  const workflow = fs.readFileSync(workflowPath, 'utf8');

  assert.match(workflow, /publish-npm-package:\s*\n/);
  assert.match(workflow, /needs:\s*publish-runtime-release/);
  assert.match(workflow, /id-token:\s*write/);
  assert.match(workflow, /contents:\s*read/);
  assert.match(workflow, /uses:\s*actions\/setup-node@v6/);
  assert.match(workflow, /node-version:\s*['"]24['"]/);
  assert.match(workflow, /registry-url:\s*['"]https:\/\/registry\.npmjs\.org['"]/);
  assert.match(workflow, /package-manager-cache:\s*false/);
  assert.match(workflow, /npm publish --access public/);
  assert.doesNotMatch(workflow, /NODE_AUTH_TOKEN|NPM_TOKEN|_authToken/);
});

test('trusted publish validates the package identity and release tag before publishing', () => {
  const workflow = fs.readFileSync(workflowPath, 'utf8');
  const packageMetadata = JSON.parse(fs.readFileSync(packagePath, 'utf8'));

  assert.equal(packageMetadata.name, '@cyhuh/media-bridge');
  assert.equal(packageMetadata.repository.url, 'git+https://github.com/cyhuh7950/media-bridge.git');
  assert.equal(packageMetadata.publishConfig?.access, 'public');
  assert.match(workflow, /package_name=.*package\.json/);
  assert.match(workflow, /package_version=.*package\.json/);
  assert.match(workflow, /release-v\$package_version/);
  assert.match(workflow, /npm_version=.*npm --version/);
  assert.match(workflow, /11\.5\.1/);
});
