const crypto = require('node:crypto');
const fs = require('node:fs');
const fsp = fs.promises;
const os = require('node:os');
const path = require('node:path');
const { execFile } = require('node:child_process');
const { promisify } = require('node:util');

const execFileAsync = promisify(execFile);

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
  platformKey,
  resolveRuntime,
  runtimeDir,
};
