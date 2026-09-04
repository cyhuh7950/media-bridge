const crypto = require('node:crypto');
const fs = require('node:fs');
const fsp = fs.promises;
const os = require('node:os');
const path = require('node:path');
const { execFile } = require('node:child_process');
const { promisify } = require('node:util');
const packageMetadata = require('../package.json');

const execFileAsync = promisify(execFile);
const defaultManifestPath = path.join(__dirname, '..', 'runtime-manifest.json');

function platformKey(platform = process.platform, arch = process.arch) {
  const supported = new Set(['linux-x64', 'linux-arm64', 'win32-x64', 'darwin-x64', 'darwin-arm64']);
  const key = `${platform}-${arch}`;
  if (!supported.has(key)) throw new Error(`unsupported Media Bridge runtime platform: ${key}`);
  return key;
}

function runtimeDir(homeDir = os.homedir()) {
  return path.join(homeDir, '.media-bridge', 'runtime');
}

function runtimeCommand(root, platform) {
  return path.join(root, 'bin', platform === 'win32' ? 'python.exe' : 'python');
}

function isAllowedArtifactUrl(raw) {
  let parsed;
  try { parsed = new URL(raw); } catch { return false; }
  return parsed.protocol === 'https:' || (parsed.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(parsed.hostname));
}

function loadRuntimeManifest({ manifestPath = defaultManifestPath, packageVersion } = {}) {
  let manifest;
  try {
    manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
  } catch (error) {
    throw new Error(`runtime manifest is unavailable or invalid: ${error.message}`);
  }
  if (manifest?.schemaVersion !== 1) throw new Error('runtime manifest schema is unsupported');
  if (packageVersion && manifest.packageVersion !== packageVersion) {
    throw new Error('runtime manifest package version does not match the npm package');
  }
  if (!manifest.artifacts || typeof manifest.artifacts !== 'object') {
    throw new Error('runtime manifest artifacts are missing');
  }
  return manifest;
}

function isSafeRelativeCommand(command) {
  if (typeof command !== 'string' || command.length === 0) return false;
  if (path.posix.isAbsolute(command) || path.win32.isAbsolute(command)) return false;
  const segments = command.replaceAll('\\', '/').split('/');
  return !segments.includes('..') && !segments.includes('') && !segments.includes('.');
}

function selectArtifact({ manifest, packageVersion, platform = process.platform, arch = process.arch }) {
  if (manifest?.schemaVersion !== 1) throw new Error('runtime manifest schema is unsupported');
  if (packageVersion && manifest.packageVersion !== packageVersion) {
    throw new Error('runtime manifest package version does not match the npm package');
  }
  const key = platformKey(platform, arch);
  const artifact = manifest?.artifacts?.[key];
  if (!artifact) throw new Error(`runtime artifact is not available for ${key}`);
  if (!artifact.published) throw new Error(`runtime artifact is not published for ${key}`);
  if (artifact.version !== manifest.packageVersion) throw new Error('runtime artifact version does not match manifest');
  if (!isAllowedArtifactUrl(artifact.url)) throw new Error('runtime artifact URL must use HTTPS or loopback HTTP');
  if (!/^[a-f0-9]{64}$/i.test(artifact.sha256 || '')) throw new Error('runtime artifact SHA-256 is required');
  if (artifact.archive !== 'tar.gz') throw new Error('runtime artifact archive must be tar.gz');
  if (!isSafeRelativeCommand(artifact.command)) throw new Error('runtime artifact command must be a safe relative path');
  if (typeof artifact.python !== 'boolean') throw new Error('runtime artifact python mode is required');
  return { key, ...artifact };
}

async function downloadArtifact(url, destination, fetchImpl = fetch) {
  const response = await fetchImpl(url);
  if (!response.ok) throw new Error(`runtime artifact download failed: HTTP ${response.status}`);
  await fsp.writeFile(destination, Buffer.from(await response.arrayBuffer()));
}

async function extractArtifact(archive, destination, execFileImpl = execFileAsync) {
  await fsp.mkdir(destination, { recursive: true, mode: 0o700 });
  let tarCommand = 'tar';
  if (process.platform === 'win32') {
    const windowsRoot = process.env.SystemRoot || process.env.WINDIR;
    if (!windowsRoot) throw new Error('runtime artifact extraction failed: Windows system root is unavailable');
    tarCommand = path.join(windowsRoot, 'System32', 'tar.exe');
    if (!fs.existsSync(tarCommand)) {
      throw new Error(`runtime artifact extraction failed: Windows system tar is unavailable: ${tarCommand}`);
    }
  }
  try {
    await execFileImpl(tarCommand, ['-xzf', archive, '-C', destination]);
  } catch (error) {
    throw new Error(`runtime artifact extraction failed: ${error.message}`);
  }
}

function artifactCommand(root, artifact) {
  const target = path.resolve(root, ...artifact.command.replaceAll('\\', '/').split('/'));
  const relative = path.relative(root, target);
  if (!relative || relative.startsWith('..') || path.isAbsolute(relative)) {
    throw new Error('runtime artifact command escapes the runtime directory');
  }
  return target;
}

function verifiedMetadata(artifact) {
  return {
    schemaVersion: 1,
    platform: artifact.key,
    version: artifact.version,
    sha256: artifact.sha256.toLowerCase(),
    command: artifact.command,
    python: artifact.python,
  };
}

function readVerified(root) {
  try {
    return JSON.parse(fs.readFileSync(path.join(root, '.verified.json'), 'utf8'));
  } catch {
    return null;
  }
}

function metadataMatches(actual, expected) {
  return actual && Object.keys(expected).every((key) => actual[key] === expected[key]);
}

async function installArtifact({
  homeDir,
  root = runtimeDir(homeDir),
  artifact,
  fetchImpl = fetch,
  execFileImpl = execFileAsync,
}) {
  const parent = path.dirname(root);
  const token = `${process.pid}-${Date.now()}`;
  const staging = path.join(parent, `.runtime-${token}`);
  const backup = path.join(parent, `.runtime-backup-${token}`);
  const archive = path.join(parent, `.runtime-${token}.tar.gz`);
  let movedPrevious = false;
  try {
    await fsp.mkdir(parent, { recursive: true, mode: 0o700 });
    await downloadArtifact(artifact.url, archive, fetchImpl);
    const digest = crypto.createHash('sha256').update(await fsp.readFile(archive)).digest('hex');
    if (digest.toLowerCase() !== artifact.sha256.toLowerCase()) {
      throw new Error('runtime artifact checksum mismatch');
    }
    await extractArtifact(archive, staging, execFileImpl);
    const stagedCommand = artifactCommand(staging, artifact);
    let commandStat;
    try { commandStat = await fsp.stat(stagedCommand); } catch { commandStat = null; }
    if (!commandStat?.isFile()) throw new Error('runtime artifact command is missing or unavailable');
    await fsp.access(stagedCommand, fs.constants.X_OK);
    await fsp.writeFile(
      path.join(staging, '.verified.json'),
      `${JSON.stringify(verifiedMetadata(artifact), null, 2)}\n`,
      { mode: 0o600 },
    );
    if (fs.existsSync(root)) {
      await fsp.rename(root, backup);
      movedPrevious = true;
    }
    await fsp.rename(staging, root);
    if (movedPrevious) await fsp.rm(backup, { recursive: true, force: true });
    return {
      command: artifactCommand(root, artifact),
      args: [],
      python: artifact.python,
    };
  } catch (error) {
    await fsp.rm(staging, { recursive: true, force: true });
    if (movedPrevious && !fs.existsSync(root) && fs.existsSync(backup)) {
      await fsp.rename(backup, root);
    }
    throw error;
  } finally {
    await fsp.rm(archive, { force: true });
  }
}

async function resolveRuntime({
  homeDir = os.homedir(),
  env = process.env,
  platform = process.platform,
  arch = process.arch,
  fetchImpl = fetch,
  execFileImpl = execFileAsync,
  packageVersion = packageMetadata.version,
} = {}) {
  const key = platformKey(platform, arch);
  if (env.MEDIA_BRIDGE_RUNTIME_COMMAND) {
    const pythonSetting = env.MEDIA_BRIDGE_RUNTIME_PYTHON;
    if (pythonSetting !== undefined && !['true', 'false'].includes(pythonSetting)) {
      throw new Error('MEDIA_BRIDGE_RUNTIME_PYTHON must be true or false');
    }
    return {
      command: env.MEDIA_BRIDGE_RUNTIME_COMMAND,
      args: [],
      env: { ...env },
      python: pythonSetting === undefined ? true : pythonSetting === 'true',
    };
  }
  const root = env.MEDIA_BRIDGE_RUNTIME_DIR || runtimeDir(homeDir);
  let artifact;
  if (env.MEDIA_BRIDGE_RUNTIME_URL) {
    artifact = {
      key,
      version: packageVersion,
      published: true,
      url: env.MEDIA_BRIDGE_RUNTIME_URL,
      sha256: env.MEDIA_BRIDGE_RUNTIME_SHA256,
      archive: 'tar.gz',
      command: `bin/${platform === 'win32' ? 'python.exe' : 'python'}`,
      python: true,
    };
    if (!isAllowedArtifactUrl(artifact.url)) throw new Error('runtime artifact URL must use HTTPS or loopback HTTP');
    if (!/^[a-f0-9]{64}$/i.test(artifact.sha256 || '')) throw new Error('runtime artifact SHA-256 is required');
  } else {
    const manifest = loadRuntimeManifest({
      manifestPath: env.MEDIA_BRIDGE_RUNTIME_MANIFEST || defaultManifestPath,
      packageVersion,
    });
    artifact = selectArtifact({ manifest, packageVersion, platform, arch });
  }
  const expectedMetadata = verifiedMetadata(artifact);
  let command = artifactCommand(root, artifact);
  if (!fs.existsSync(command) || !metadataMatches(readVerified(root), expectedMetadata)) {
    const installed = await installArtifact({ homeDir, root, artifact, fetchImpl, execFileImpl });
    command = installed.command;
  }
  if (!fs.existsSync(command)) throw new Error(`Media Bridge runtime artifact is not available for ${key}`);
  const runtimeEnv = { ...env, MEDIA_BRIDGE_RUNTIME_PLATFORM: key };
  return { command, args: [], env: runtimeEnv, python: artifact.python };
}

module.exports = {
  loadRuntimeManifest,
  installArtifact,
  platformKey,
  resolveRuntime,
  runtimeDir,
  selectArtifact,
};
