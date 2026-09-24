const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const test = require('node:test');
const { once } = require('node:events');

const root = path.resolve(__dirname, '../..');
const workflowRoot = path.join(root, '.github', 'workflows');
const candidateScript = path.join(root, 'packaging', 'npm', 'scripts', 'assemble-candidate.cjs');
const installVerifierScript = path.join(root, 'packaging', 'npm', 'scripts', 'verify-candidate-install.cjs');

test('each native runtime builder accepts a version and exact source commit through workflow_call', () => {
  for (const name of [
    'build-runtime-linux-x64.yml',
    'build-runtime-linux-arm64.yml',
    'build-runtime-win32-x64.yml',
  ]) {
    const workflow = fs.readFileSync(path.join(workflowRoot, name), 'utf8');
    assert.match(workflow, /workflow_call:/, `${name} must be reusable`);
    assert.match(workflow, /source_commit:/, `${name} must accept source_commit`);
    assert.match(workflow, /version:/, `${name} must accept version`);
    assert.match(workflow, /ref:\s*\$\{\{\s*inputs\.source_commit\s*\|\|\s*github\.sha\s*\}\}/,
      `${name} must check out the requested source commit`);
    const versionInputCheck = workflow.indexOf(name.includes('win32')
      ? "if ($env:INPUT_VERSION)" : 'if [[ -n "$INPUT_VERSION" ]]');
    assert.ok(versionInputCheck >= 0 && versionInputCheck < workflow.indexOf('GITHUB_REF_TYPE'),
      `${name} must prefer the reusable workflow version input over caller tag parsing`);
  }
});

test('each native verifier records the runtime version in its evidence', () => {
  for (const name of [
    'verify-linux-x64.sh',
    'verify-linux-arm64.sh',
    'verify-win32-x64.ps1',
  ]) {
    const verifier = fs.readFileSync(path.join(root, 'packaging', 'runtime', name), 'utf8');
    assert.match(verifier, /runtimeVersion/, `${name} must record the verified runtime version`);
  }
});

test('candidate workflow is limited to the approved branch and read-only permissions', () => {
  const file = path.join(workflowRoot, 'build-npm-runtime-candidate.yml');
  assert.ok(fs.existsSync(file), 'candidate orchestration workflow must exist');
  const workflow = fs.readFileSync(file, 'utf8');
  assert.match(workflow, /codex\/installed-reasoning-level-config/);
  assert.match(workflow, /contents:\s*read/);
  assert.match(workflow, /actions:\s*read/);
  assert.doesNotMatch(workflow, /contents:\s*write|id-token:\s*write|npm publish|createRelease/);
  for (const platform of ['linux-x64', 'linux-arm64', 'win32-x64']) {
    assert.ok(workflow.includes(platform), `candidate must build ${platform}`);
  }
  for (const builder of ['build-runtime-linux-x64.yml', 'build-runtime-linux-arm64.yml', 'build-runtime-win32-x64.yml']) {
    assert.ok(workflow.includes(builder), `candidate must call ${builder}`);
  }
  assert.match(workflow, /actions\/upload-artifact@v4/);
  assert.match(workflow, /actions\/download-artifact@v4/);
  assert.match(workflow, /verify-candidate-install\.cjs/);
  assert.match(workflow, /github\.sha/);
  assert.match(workflow, /0\.1\.14/);
});

test('public release workflow is version-driven and npm publication requires its exact release tag', () => {
  const workflow = fs.readFileSync(path.join(workflowRoot, 'publish-npm-runtime-release.yml'), 'utf8');
  assert.match(workflow, /release-v\*/);
  assert.match(workflow, /Manual dispatch is validation-only/);
  assert.match(workflow, /release-v\(\[0-9\]/);
  assert.match(workflow, /package_version/);
  assert.match(workflow, /Check out exact release source/);
  assert.match(workflow, /source_commit:\s*\$\{\{\s*github\.sha\s*\}\}/);
  assert.match(workflow, /assemble-candidate\.cjs/);
  assert.ok(workflow.includes('media-bridge-release-${{ needs.prepare-release.outputs.version }}-${{ github.sha }}'));
  assert.match(workflow, /publish-runtime-release:[\s\S]*?if:\s*github\.ref_type\s*==\s*'tag'/);
  assert.match(workflow, /publish-npm-package:[\s\S]*?if:\s*github\.ref_type\s*==\s*'tag'/);
  assert.doesNotMatch(workflow, /VERSION:\s*0\.1\.13|TAG:\s*v0\.1\.13|SOURCE_COMMIT:\s*5e0f295|workflow_dispatch:[\s\S]{0,250}contents:\s*write/);
});

test('candidate assembly binds all runtime archives to one version, source commit, and verified evidence', async (context) => {
  assert.ok(fs.existsSync(candidateScript), 'candidate assembler must exist');
  const { assembleCandidate } = require(candidateScript);
  const version = '0.1.14';
  const sourceCommit = 'a'.repeat(40);
  const platforms = {
    'linux-arm64': { command: 'bin/media-bridge-runtime', platform: 'linux', arch: 'arm64' },
    'linux-x64': { command: 'bin/media-bridge-runtime', platform: 'linux', arch: 'x64' },
    'win32-x64': { command: 'bin/media-bridge-runtime.exe', platform: 'win32', arch: 'x64' },
  };

  async function fixture(name, mutate) {
    const tempRoot = fs.mkdtempSync(path.join(require('node:os').tmpdir(), 'mb-candidate-assembly-'));
    const artifactDirectories = {};
    try {
      for (const [platform, details] of Object.entries(platforms)) {
        const directory = path.join(tempRoot, platform);
        fs.mkdirSync(directory, { recursive: true });
        const artifactName = `media-bridge-runtime-${version}-${platform}.tar.gz`;
        const artifactPath = path.join(directory, artifactName);
        fs.writeFileSync(artifactPath, `runtime ${platform} ${version}`);
        const sha256 = require('node:crypto').createHash('sha256').update(fs.readFileSync(artifactPath)).digest('hex');
        fs.writeFileSync(`${artifactPath}.sha256`, `${sha256}  ${artifactName}\n`);
        const entry = {
          version,
          published: true,
          url: `http://127.0.0.1:18080/${artifactName}`,
          sha256,
          archive: 'tar.gz',
          command: details.command,
          python: false,
        };
        const manifest = { schemaVersion: 1, packageVersion: version, artifacts: { [platform]: entry } };
        fs.writeFileSync(path.join(directory, 'runtime-manifest.json'), JSON.stringify(manifest));
        const evidence = {
          schemaVersion: 1,
          sourceCommit,
          packageVersion: version,
          runtimeVersion: version,
          artifactName,
          sha256,
          platform,
          healthStatus: 200,
        };
        fs.writeFileSync(path.join(directory, 'verification-result.json'), JSON.stringify(evidence));
        artifactDirectories[platform] = directory;
      }
      await mutate?.({ tempRoot, artifactDirectories, version, sourceCommit });
      return { tempRoot, artifactDirectories };
    } catch (error) {
      fs.rmSync(tempRoot, { recursive: true, force: true });
      throw error;
    }
  }

  const valid = await fixture('valid');
  try {
    const outputDirectory = path.join(valid.tempRoot, 'candidate-output');
    const result = assembleCandidate({
      packageRoot: path.join(root, 'packaging', 'npm'),
      artifactDirectories: valid.artifactDirectories,
      sourceCommit,
      version,
      outputDirectory,
    });
    const packageMetadata = JSON.parse(fs.readFileSync(path.join(result.packageDirectory, 'package.json'), 'utf8'));
    const manifest = JSON.parse(fs.readFileSync(path.join(result.packageDirectory, 'runtime-manifest.json'), 'utf8'));
    assert.equal(packageMetadata.version, version);
    assert.equal(manifest.packageVersion, version);
    assert.equal(manifest.artifacts['linux-x64'].version, version);
    assert.match(manifest.artifacts['linux-x64'].url, new RegExp(`/releases/download/v${version}/`));
    assert.equal(JSON.parse(fs.readFileSync(path.join(result.runtimeDirectory, 'runtime-manifest.json'), 'utf8')).packageVersion,
      version, 'release assets must include the assembled candidate manifest');
    assert.equal(JSON.parse(fs.readFileSync(result.evidencePath, 'utf8')).sourceCommit, sourceCommit);
    const npmCli = [
      path.join(path.dirname(process.execPath), 'node_modules', 'npm', 'bin', 'npm-cli.js'),
      path.resolve(path.dirname(process.execPath), '..', 'lib', 'node_modules', 'npm', 'bin', 'npm-cli.js'),
    ].find((candidate) => fs.existsSync(candidate));
    assert.ok(npmCli, 'npm CLI must be available beside the configured Node.js runtime');
    const packed = JSON.parse(execFileSync(process.execPath, [npmCli,
      'pack', '--json', '--cache', path.join(valid.tempRoot, 'npm-cache'),
      '--pack-destination', valid.tempRoot, result.packageDirectory,
    ], { encoding: 'utf8' }));
    assert.equal(packed.length, 1);
    assert.equal(packed[0].version, version);
    assert.ok(packed[0].files.some((file) => file.path === 'runtime-manifest.json'));
    assert.ok(packed[0].files.every((file) => !/test|secret|candidate-evidence|node_modules/i.test(file.path)));
    assert.ok(fs.statSync(path.join(valid.tempRoot, packed[0].filename)).isFile());
    assert.equal(JSON.parse(fs.readFileSync(path.join(root, 'packaging', 'npm', 'runtime-manifest.json'), 'utf8')).packageVersion,
      '0.1.13', 'published manifest must remain unchanged');
  } finally {
    fs.rmSync(valid.tempRoot, { recursive: true, force: true });
  }

  const invalidCases = [
    ['missing platform', async ({ artifactDirectories }) => { delete artifactDirectories['linux-arm64']; }],
    ['mismatched source commit', async ({ tempRoot, artifactDirectories }) => {
      const file = path.join(artifactDirectories['linux-x64'], 'verification-result.json');
      const evidence = JSON.parse(fs.readFileSync(file, 'utf8'));
      evidence.sourceCommit = 'b'.repeat(40);
      fs.writeFileSync(file, JSON.stringify(evidence));
    }],
    ['mismatched runtime version', async ({ artifactDirectories }) => {
      const file = path.join(artifactDirectories['win32-x64'], 'verification-result.json');
      const evidence = JSON.parse(fs.readFileSync(file, 'utf8'));
      evidence.runtimeVersion = '0.1.13';
      fs.writeFileSync(file, JSON.stringify(evidence));
    }],
    ['incorrect checksum evidence', async ({ artifactDirectories }) => {
      const file = path.join(artifactDirectories['linux-x64'], 'verification-result.json');
      const evidence = JSON.parse(fs.readFileSync(file, 'utf8'));
      evidence.sha256 = '0'.repeat(64);
      fs.writeFileSync(file, JSON.stringify(evidence));
    }],
    ['failed runtime health evidence', async ({ artifactDirectories }) => {
      const file = path.join(artifactDirectories['linux-arm64'], 'verification-result.json');
      const evidence = JSON.parse(fs.readFileSync(file, 'utf8'));
      evidence.healthStatus = 503;
      fs.writeFileSync(file, JSON.stringify(evidence));
    }],
    ['incorrect artifact filename', async ({ artifactDirectories }) => {
      const directory = artifactDirectories['linux-x64'];
      const oldPath = path.join(directory, `media-bridge-runtime-${version}-linux-x64.tar.gz`);
      const newPath = path.join(directory, `media-bridge-runtime-${version}-linux-arm64.tar.gz`);
      fs.renameSync(oldPath, newPath);
    }],
    ['mismatched manifest version', async ({ artifactDirectories }) => {
      const file = path.join(artifactDirectories['linux-arm64'], 'runtime-manifest.json');
      const manifest = JSON.parse(fs.readFileSync(file, 'utf8'));
      manifest.packageVersion = '0.1.13';
      fs.writeFileSync(file, JSON.stringify(manifest));
    }],
    ['mismatched checksum sidecar', async ({ artifactDirectories }) => {
      const artifactPath = path.join(artifactDirectories['win32-x64'], `media-bridge-runtime-${version}-win32-x64.tar.gz`);
      fs.writeFileSync(`${artifactPath}.sha256`, `${'0'.repeat(64)}  ${path.basename(artifactPath)}\n`);
    }],
  ];
  for (const [name, mutate] of invalidCases) {
    await context.test(name, async () => {
      const invalid = await fixture(name, mutate);
      try {
        assert.throws(() => assembleCandidate({
          packageRoot: path.join(root, 'packaging', 'npm'),
          artifactDirectories: invalid.artifactDirectories,
          sourceCommit,
          version,
          outputDirectory: path.join(invalid.tempRoot, 'candidate-output'),
        }));
      } finally {
        fs.rmSync(invalid.tempRoot, { recursive: true, force: true });
      }
    });
  }
});

test('candidate install verification rewrites only the selected platform URL to loopback', () => {
  assert.ok(fs.existsSync(installVerifierScript), 'candidate install verifier must exist');
  const { createLoopbackManifest } = require(installVerifierScript);
  const manifest = {
    schemaVersion: 1,
    packageVersion: '0.1.14',
    artifacts: Object.fromEntries(['linux-arm64', 'linux-x64', 'win32-x64'].map((platform) => [platform, {
      version: '0.1.14',
      published: true,
      url: `https://github.com/cyhuh7950/media-bridge/releases/download/v0.1.14/${platform}.tar.gz`,
      sha256: 'b'.repeat(64),
      archive: 'tar.gz',
      command: platform === 'win32-x64' ? 'bin/media-bridge-runtime.exe' : 'bin/media-bridge-runtime',
      python: false,
    }])),
  };
  const actual = createLoopbackManifest({
    manifest,
    platform: 'win32-x64',
    url: 'http://127.0.0.1:18648/media-bridge-runtime-0.1.14-win32-x64.tar.gz',
  });
  assert.equal(actual.artifacts['win32-x64'].url,
    'http://127.0.0.1:18648/media-bridge-runtime-0.1.14-win32-x64.tar.gz');
  assert.match(actual.artifacts['linux-x64'].url, /^https:\/\//);
  assert.match(manifest.artifacts['win32-x64'].url, /^https:\/\//, 'input manifest must not be mutated');
  assert.throws(() => createLoopbackManifest({ manifest, platform: 'win32-x64', url: 'https://example.com/runtime.tgz' }), /loopback/i);
});

test('candidate settings POST sends its same-origin Origin header', async () => {
  const { postSameOriginJson } = require(installVerifierScript);
  let receivedOrigin;
  const server = http.createServer((request, response) => {
    receivedOrigin = request.headers.origin;
    response.writeHead(200, { 'content-type': 'application/json' });
    response.end(JSON.stringify({ saved: true }));
  });
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  const url = `http://127.0.0.1:${server.address().port}/api/settings`;

  try {
    const response = await postSameOriginJson(url, { reasoningEffort: 'high' });
    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), { saved: true });
    assert.equal(receivedOrigin, `http://127.0.0.1:${server.address().port}`);
  } finally {
    await new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  }
});
