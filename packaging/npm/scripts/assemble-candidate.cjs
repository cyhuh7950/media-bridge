'use strict';

const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

const platforms = {
  'linux-arm64': { command: 'bin/media-bridge-runtime', platform: 'linux', arch: 'arm64' },
  'linux-x64': { command: 'bin/media-bridge-runtime', platform: 'linux', arch: 'x64' },
  'win32-x64': { command: 'bin/media-bridge-runtime.exe', platform: 'win32', arch: 'x64' },
};

function sha256(filePath) {
  return crypto.createHash('sha256').update(fs.readFileSync(filePath)).digest('hex');
}

function readJson(filePath, label) {
  try {
    return JSON.parse(fs.readFileSync(filePath, 'utf8'));
  } catch (error) {
    throw new Error(`${label} is missing or invalid: ${error.message}`);
  }
}

function validatePlatformArtifact({ platform, directory, version, sourceCommit }) {
  const details = platforms[platform];
  if (!details || typeof directory !== 'string'
      || !fs.statSync(directory, { throwIfNoEntry: false })?.isDirectory()) {
    throw new Error(`${platform} artifact directory is missing`);
  }
  const artifactName = `media-bridge-runtime-${version}-${platform}.tar.gz`;
  const artifactPath = path.join(directory, artifactName);
  const checksumPath = `${artifactPath}.sha256`;
  if (!fs.statSync(artifactPath, { throwIfNoEntry: false })?.isFile()) {
    throw new Error(`${platform} runtime archive is missing or incorrectly named`);
  }
  if (!fs.statSync(checksumPath, { throwIfNoEntry: false })?.isFile()) {
    throw new Error(`${platform} checksum file is missing`);
  }
  const digest = sha256(artifactPath);
  const checksum = fs.readFileSync(checksumPath, 'utf8').trim().match(/^([a-f0-9]{64})\s+\*?(.+)$/i);
  if (!checksum || checksum[1].toLowerCase() !== digest || checksum[2] !== artifactName) {
    throw new Error(`${platform} runtime archive checksum does not match its sidecar`);
  }

  const manifest = readJson(path.join(directory, 'runtime-manifest.json'), `${platform} runtime manifest`);
  const entry = manifest.artifacts?.[platform];
  if (manifest.schemaVersion !== 1 || manifest.packageVersion !== version
      || entry?.version !== version || entry.sha256?.toLowerCase() !== digest
      || entry.archive !== 'tar.gz' || entry.command !== details.command || entry.python !== false) {
    throw new Error(`${platform} runtime manifest does not match the candidate archive`);
  }

  const verification = readJson(path.join(directory, 'verification-result.json'), `${platform} verification evidence`);
  if (verification.schemaVersion !== 1
      || verification.sourceCommit?.toLowerCase() !== sourceCommit.toLowerCase()
      || verification.packageVersion !== version
      || verification.runtimeVersion !== version
      || verification.artifactName !== artifactName
      || verification.sha256?.toLowerCase() !== digest
      || verification.platform !== platform
      || verification.healthStatus !== 200) {
    throw new Error(`${platform} runtime verification evidence does not match the candidate`);
  }
  return { artifactName, artifactPath, digest, bytes: fs.statSync(artifactPath).size, verification };
}

function assembleCandidate({ packageRoot, artifactDirectories, sourceCommit, version, outputDirectory }) {
  if (!/^[0-9]+\.[0-9]+\.[0-9]+$/.test(version || '')) throw new Error('candidate version must use x.y.z format');
  if (!/^[a-f0-9]{40}$/i.test(sourceCommit || '')) throw new Error('source commit must be a full 40-character SHA');
  if (!path.isAbsolute(packageRoot || '') || !path.isAbsolute(outputDirectory || '')) {
    throw new Error('packageRoot and outputDirectory must be absolute paths');
  }
  if (!fs.statSync(packageRoot, { throwIfNoEntry: false })?.isDirectory()) throw new Error('npm package root is missing');
  if (fs.existsSync(outputDirectory)) throw new Error('candidate output directory must not already exist');
  const packageMetadata = readJson(path.join(packageRoot, 'package.json'), 'npm package metadata');
  if (packageMetadata.name !== '@cyhuh/media-bridge') throw new Error('unexpected npm package identity');
  if (packageMetadata.version !== version) throw new Error('candidate version does not match npm package metadata');
  const baseManifest = readJson(path.join(packageRoot, 'runtime-manifest.json'), 'published runtime manifest');
  if (baseManifest.schemaVersion !== 1) throw new Error('runtime manifest schema is unsupported');

  const validated = {};
  for (const platform of Object.keys(platforms)) {
    validated[platform] = validatePlatformArtifact({
      platform,
      directory: artifactDirectories?.[platform],
      version,
      sourceCommit,
    });
  }

  fs.mkdirSync(outputDirectory, { recursive: false });
  const packageDirectory = path.join(outputDirectory, 'package');
  const runtimeDirectory = path.join(outputDirectory, 'runtime-artifacts');
  fs.cpSync(packageRoot, packageDirectory, {
    recursive: true,
    filter: (source) => !source.split(path.sep).some((segment) => ['node_modules', '.git'].includes(segment)),
  });
  fs.mkdirSync(runtimeDirectory);

  const candidatePackage = readJson(path.join(packageDirectory, 'package.json'), 'staged npm package metadata');
  candidatePackage.version = version;
  fs.writeFileSync(path.join(packageDirectory, 'package.json'), `${JSON.stringify(candidatePackage, null, 2)}\n`);
  const manifest = structuredClone(baseManifest);
  manifest.packageVersion = version;
  for (const [platform, details] of Object.entries(platforms)) {
    const item = validated[platform];
    manifest.artifacts[platform] = {
      ...(manifest.artifacts?.[platform] || {}),
      version,
      published: true,
      url: `https://github.com/cyhuh7950/media-bridge/releases/download/v${version}/${item.artifactName}`,
      sha256: item.digest,
      archive: 'tar.gz',
      command: details.command,
      python: false,
    };
    fs.copyFileSync(item.artifactPath, path.join(runtimeDirectory, item.artifactName));
    fs.copyFileSync(`${item.artifactPath}.sha256`, path.join(runtimeDirectory, `${item.artifactName}.sha256`));
    fs.writeFileSync(
      path.join(runtimeDirectory, `verification-result-${platform}.json`),
      `${JSON.stringify(item.verification, null, 2)}\n`,
    );
  }
  const manifestPath = path.join(packageDirectory, 'runtime-manifest.json');
  fs.writeFileSync(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);
  fs.copyFileSync(manifestPath, path.join(runtimeDirectory, 'runtime-manifest.json'));
  const evidencePath = path.join(outputDirectory, 'candidate-evidence.json');
  const evidence = {
    schemaVersion: 1,
    package: packageMetadata.name,
    version,
    sourceCommit: sourceCommit.toLowerCase(),
    platforms: Object.fromEntries(Object.entries(validated).map(([platform, item]) => [platform, {
      artifactName: item.artifactName,
      bytes: item.bytes,
      sha256: item.digest,
      healthStatus: item.verification.healthStatus,
    }])),
  };
  fs.writeFileSync(evidencePath, `${JSON.stringify(evidence, null, 2)}\n`);
  return { outputDirectory, packageDirectory, manifestPath, evidencePath, runtimeDirectory };
}

function parseArgs(args) {
  const result = {};
  for (let index = 0; index < args.length; index += 2) {
    const key = args[index];
    if (!key?.startsWith('--') || !args[index + 1]) throw new Error('expected --name value arguments');
    result[key.slice(2)] = args[index + 1];
  }
  const required = ['package-root', 'linux-arm64', 'linux-x64', 'win32-x64', 'source-commit', 'version', 'output-directory'];
  for (const key of required) {
    if (!result[key]) throw new Error(`--${key} is required`);
  }
  return result;
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  const result = assembleCandidate({
    packageRoot: args['package-root'],
    artifactDirectories: {
      'linux-arm64': args['linux-arm64'],
      'linux-x64': args['linux-x64'],
      'win32-x64': args['win32-x64'],
    },
    sourceCommit: args['source-commit'],
    version: args.version,
    outputDirectory: args['output-directory'],
  });
  process.stdout.write(`${JSON.stringify(result)}\n`);
}

if (require.main === module) {
  try {
    main();
  } catch (error) {
    process.stderr.write(`${error.stack || error}\n`);
    process.exitCode = 1;
  }
}

module.exports = { assembleCandidate };
