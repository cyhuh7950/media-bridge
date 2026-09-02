'use strict';

const crypto = require('node:crypto');
const fs = require('node:fs');
const fsp = require('node:fs/promises');
const http = require('node:http');
const path = require('node:path');
const { once } = require('node:events');

const runtimeApi = require('../npm/lib/runtime.cjs');

function requireAbsolute(value, name) {
  if (!path.isAbsolute(value || '')) throw new Error(`${name} must be an absolute path`);
  return path.resolve(value);
}

async function sha256(filePath) {
  const content = await fsp.readFile(filePath);
  return crypto.createHash('sha256').update(content).digest('hex');
}

async function main() {
  const [artifactDirectoryArg, testRootArg] = process.argv.slice(2);
  const artifactDirectory = requireAbsolute(artifactDirectoryArg, 'ArtifactDirectory');
  const testRoot = requireAbsolute(testRootArg, 'TestRoot');
  const manifestPath = path.join(artifactDirectory, 'runtime-manifest.json');
  const sourceManifest = JSON.parse(await fsp.readFile(manifestPath, 'utf8'));
  const archives = (await fsp.readdir(artifactDirectory))
    .filter((name) => /^media-bridge-runtime-.+-win32-x64\.tar\.gz$/.test(name));
  if (archives.length !== 1) throw new Error('expected exactly one win32-x64 runtime archive');
  const artifactPath = path.join(artifactDirectory, archives[0]);
  const artifactSha = await sha256(artifactPath);

  await fsp.mkdir(testRoot, { recursive: false });
  const homeDir = path.join(testRoot, 'home');
  const qaManifestPath = path.join(testRoot, 'runtime-manifest.json');
  const server = http.createServer((request, response) => {
    if (request.url !== `/${archives[0]}`) {
      response.writeHead(404).end();
      return;
    }
    response.writeHead(200, { 'content-type': 'application/gzip' });
    fs.createReadStream(artifactPath).pipe(response);
  });
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');

  try {
    const port = server.address().port;
    const validManifest = structuredClone(sourceManifest);
    const validArtifact = validManifest.artifacts['win32-x64'];
    validArtifact.url = `http://127.0.0.1:${port}/${archives[0]}`;
    validArtifact.sha256 = artifactSha;
    validArtifact.published = true;
    await fsp.writeFile(qaManifestPath, `${JSON.stringify(validManifest, null, 2)}\n`);

    const runtime = await runtimeApi.resolveRuntime({
      homeDir,
      env: { MEDIA_BRIDGE_RUNTIME_MANIFEST: qaManifestPath },
      platform: 'win32',
      arch: 'x64',
    });
    if (runtime.python !== false) throw new Error('managed runtime unexpectedly requires Python');
    const installedShaBefore = await sha256(runtime.command);
    const verifiedPath = path.join(runtimeApi.runtimeDir(homeDir), '.verified.json');
    const verifiedBefore = await fsp.readFile(verifiedPath, 'utf8');

    const badManifest = structuredClone(validManifest);
    badManifest.artifacts['win32-x64'].sha256 = '0'.repeat(64);
    await fsp.writeFile(qaManifestPath, `${JSON.stringify(badManifest, null, 2)}\n`);

    let rollbackRejected = false;
    try {
      await runtimeApi.resolveRuntime({
        homeDir,
        env: { MEDIA_BRIDGE_RUNTIME_MANIFEST: qaManifestPath },
        platform: 'win32',
        arch: 'x64',
      });
    } catch (error) {
      rollbackRejected = String(error?.message || error).includes('checksum mismatch');
    }
    const installedShaAfter = await sha256(runtime.command);
    const verifiedAfter = await fsp.readFile(verifiedPath, 'utf8');
    const rollbackPreserved = rollbackRejected
      && installedShaAfter === installedShaBefore
      && verifiedAfter === verifiedBefore;
    if (!rollbackPreserved) throw new Error('checksum mismatch did not preserve the verified runtime');

    process.stdout.write(JSON.stringify({
      managedInstall: true,
      managedPython: runtime.python,
      installedCommand: path.relative(homeDir, runtime.command).replaceAll('\\', '/'),
      installedCommandSha256: installedShaBefore,
      checksumMismatchRejected: rollbackRejected,
      rollbackPreserved,
    }));
  } finally {
    server.close();
    await once(server, 'close');
  }
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});
