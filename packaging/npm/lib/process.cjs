const fs = require('node:fs');
const fsp = fs.promises;
const os = require('node:os');
const path = require('node:path');
const { execFileSync, spawn } = require('node:child_process');

function statePath(homeDir = os.homedir()) {
  return path.join(homeDir, '.media-bridge', 'service.pid');
}

function stateDirectory(homeDir) {
  return path.dirname(statePath(homeDir));
}

function isAlive(pid) {
  if (!Number.isInteger(pid) || pid < 1) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

function inspectProcessIdentity(pid, platform = process.platform) {
  if (!isAlive(pid)) return null;
  try {
    if (platform === 'linux') {
      const stat = fs.readFileSync(`/proc/${pid}/stat`, 'utf8');
      const commandEnd = stat.lastIndexOf(')');
      const fieldsAfterCommand = stat.slice(commandEnd + 2).trim().split(/\s+/);
      const startMarker = fieldsAfterCommand[19];
      const executable = fs.readlinkSync(`/proc/${pid}/exe`);
      if (!startMarker || !executable) return null;
      return { executable, startMarker: `linux:${startMarker}` };
    }
    if (platform === 'win32') {
      const script = [
        `$p = Get-Process -Id ${pid} -ErrorAction Stop`,
        '$result = [ordered]@{ executable = $p.Path; startMarker = $p.StartTime.ToUniversalTime().Ticks.ToString() }',
        '$result | ConvertTo-Json -Compress',
      ].join('; ');
      const output = execFileSync('powershell.exe', [
        '-NoProfile', '-NonInteractive', '-Command', script,
      ], { encoding: 'utf8', windowsHide: true }).trim();
      const identity = JSON.parse(output);
      if (!identity.executable || !identity.startMarker) return null;
      return identity;
    }
    const output = execFileSync('ps', [
      '-p', String(pid), '-o', 'lstart=', '-o', 'comm=',
    ], { encoding: 'utf8' }).trim();
    const match = output.match(/^(.{24})\s+(.+)$/);
    if (!match) return null;
    return { executable: match[2].trim(), startMarker: `${platform}:${match[1].trim()}` };
  } catch {
    return null;
  }
}

function normalizedExecutable(value, platform = process.platform) {
  if (!value) return '';
  const normalized = path.normalize(value);
  return platform === 'win32' ? normalized.toLowerCase() : normalized;
}

function identityMatches(recorded, current, platform = process.platform) {
  if (!recorded || !current) return false;
  return recorded.startMarker === current.startMarker
    && normalizedExecutable(recorded.executable, platform) === normalizedExecutable(current.executable, platform);
}

function readState(homeDir) {
  const target = statePath(homeDir);
  if (!fs.existsSync(target)) return null;
  try {
    const state = JSON.parse(fs.readFileSync(target, 'utf8'));
    return Number.isInteger(state.pid) ? state : null;
  } catch {
    return null;
  }
}

async function writeState(homeDir, state) {
  await fsp.mkdir(stateDirectory(homeDir), { recursive: true, mode: 0o700 });
  const target = statePath(homeDir);
  const temporary = `${target}.${process.pid}.tmp`;
  await fsp.writeFile(temporary, `${JSON.stringify(state, null, 2)}\n`, { mode: 0o600 });
  await fsp.rename(temporary, target);
}

async function startProcess({ config, runtime, homeDir = os.homedir(), portOverride } = {}) {
  const current = readStatus({ homeDir });
  if (current.running) throw new Error(`Media Bridge is already running: ${current.pid}`);
  const port = portOverride ?? config.port;
  const args = runtime.python
    ? [...(runtime.args || []), '-c', 'from media_bridge.entrypoints import run_http; run_http()']
    : [...(runtime.args || [])];
  const child = spawn(runtime.command, args, {
    detached: true,
    stdio: 'ignore',
    env: {
      ...runtime.env,
      MEDIA_BRIDGE_HTTP_HOST: config.host,
      MEDIA_BRIDGE_HTTP_PORT: String(port),
    },
  });
  try {
    await new Promise((resolve, reject) => {
      child.once('spawn', resolve);
      child.once('error', reject);
    });
    const identity = inspectProcessIdentity(child.pid);
    if (!identity) throw new Error('Media Bridge child identity could not be verified');
    const state = { pid: child.pid, command: runtime.command, identity, host: config.host, port };
    await writeState(homeDir, state);
    child.unref();
    return state;
  } catch (error) {
    if (child.pid && isAlive(child.pid)) child.kill();
    await fsp.rm(statePath(homeDir), { force: true });
    throw error;
  }
}

async function stopProcess({ homeDir = os.homedir() } = {}) {
  const state = readState(homeDir);
  if (!state) return { running: false };
  if (isAlive(state.pid)) {
    const currentIdentity = inspectProcessIdentity(state.pid);
    if (!identityMatches(state.identity, currentIdentity)) {
      await fsp.rm(statePath(homeDir), { force: true });
      return { running: false, pid: state.pid, ownershipMismatch: true };
    }
    try { process.kill(state.pid); } catch { /* process exited between checks */ }
  }
  await fsp.rm(statePath(homeDir), { force: true });
  return { running: false, pid: state.pid };
}

function readStatus({ homeDir = os.homedir() } = {}) {
  const state = readState(homeDir);
  if (!state) return { running: false };
  const running = isAlive(state.pid);
  if (!running) fs.rmSync(statePath(homeDir), { force: true });
  if (!running) return { running: false };
  const currentIdentity = inspectProcessIdentity(state.pid);
  if (!identityMatches(state.identity, currentIdentity)) {
    fs.rmSync(statePath(homeDir), { force: true });
    return { running: false, ownershipMismatch: true };
  }
  return { ...state, running: true };
}

async function checkHealth({ config, fetchImpl = fetch } = {}) {
  const url = `http://${config.host}:${config.port}/health`;
  try {
    const response = await fetchImpl(url);
    return { healthy: response.ok, status: response.status, url };
  } catch {
    return { healthy: false, status: null, url };
  }
}

module.exports = {
  checkHealth,
  identityMatches,
  inspectProcessIdentity,
  isAlive,
  readStatus,
  startProcess,
  statePath,
  stopProcess,
};
