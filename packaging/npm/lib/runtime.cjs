const crypto = require('node:crypto');
const fs = require('node:fs');
const fsp = fs.promises;
const os = require('node:os');
const path = require('node:path');
const { execFile } = require('node:child_process');
const { promisify } = require('node:util');

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

async function downloadArtifact(url, destination) {
  if (url.startsWith('file://')) {
    await fsp.copyFile(new URL(url), destination);
    return;
  }
  const response = await fetch(url);
  if (!response.ok) throw new Error(`runtime artifact download failed: HTTP ${response.status}`);
  await fsp.writeFile(destination, Buffer.from(await response.arrayBuffer()));
}

async function extractArtifact(archive, destination) {
  await fsp.mkdir(destination, { recursive: true, mode: 0o700 });
  const tarCommand = process.platform === 'win32' ? 'tar.exe' : 'tar';
  try {
    await execFileAsync(tarCommand, ['-xzf', archive, '-C', destination]);
  } catch (error) {
    throw new Error(`runtime artifact extraction failed: ${error.message}`);
  }
}

async function installArtifact({ homeDir, url, sha256, platform }) {
  if (!isAllowedArtifactUrl(url)) throw new Error('runtime artifact URL must use HTTPS or loopback HTTP');
  if (!/^[a-f0-9]{64}$/i.test(sha256 || '')) throw new Error('runtime artifact SHA-256 is required');
  const root = runtimeDir(homeDir);
  const parent = path.dirname(root);
  const staging = path.join(parent, `.runtime-${process.pid}-${Date.now()}`);
  const archive = path.join(parent, `.runtime-${process.pid}.tar.gz`);
  try {
    await fsp.mkdir(parent, { recursive: true, mode: 0o700 });
    await downloadArtifact(url, archive);
    const digest = crypto.createHash('sha256').update(await fsp.readFile(archive)).digest('hex');
    if (digest.toLowerCase() !== sha256.toLowerCase()) throw new Error('runtime artifact checksum mismatch');
    await extractArtifact(archive, staging);
    const command = runtimeCommand(staging, platform);
    await fsp.access(command, fs.constants.X_OK);
    await fsp.writeFile(path.join(staging, '.verified'), `${sha256.toLowerCase()}\n`, { mode: 0o600 });
    await fsp.rm(root, { recursive: true, force: true });
    await fsp.rename(staging, root);
    return runtimeCommand(root, platform);
  } catch (error) {
    await fsp.rm(staging, { recursive: true, force: true });
    throw error;
  } finally {
    await fsp.rm(archive, { force: true });
  }
}

async function resolveRuntime({ homeDir = os.homedir(), env = process.env, platform = process.platform, arch = process.arch } = {}) {
  const key = platformKey(platform, arch);
  if (env.MEDIA_BRIDGE_RUNTIME_COMMAND) return { command: env.MEDIA_BRIDGE_RUNTIME_COMMAND, args: [], env: { ...env }, python: true };
  const root = env.MEDIA_BRIDGE_RUNTIME_DIR || runtimeDir(homeDir);
  const command = runtimeCommand(root, platform);
  if (!fs.existsSync(command)) {
    if (!env.MEDIA_BRIDGE_RUNTIME_URL) {
      throw new Error(`Media Bridge runtime artifact is not available for ${key}`);
    }
    await installArtifact({ homeDir, url: env.MEDIA_BRIDGE_RUNTIME_URL, sha256: env.MEDIA_BRIDGE_RUNTIME_SHA256, platform });
  }
  if (!fs.existsSync(command)) throw new Error(`Media Bridge runtime artifact is not available for ${key}`);
  const runtimeEnv = { ...env, MEDIA_BRIDGE_RUNTIME_PLATFORM: key };
  return { command, args: [], env: runtimeEnv, python: true };
}

module.exports = {
  loadRuntimeManifest,
  platformKey,
  resolveRuntime,
  runtimeDir,
  selectArtifact,
};
