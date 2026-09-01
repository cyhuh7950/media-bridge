const fs = require('node:fs');
const fsp = fs.promises;
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');

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
  const current = readState(homeDir);
  if (current && isAlive(current.pid)) throw new Error(`Media Bridge is already running: ${current.pid}`);
  if (current) await fsp.rm(statePath(homeDir), { force: true });
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
  const state = { pid: child.pid, command: runtime.command, host: config.host, port };
  await writeState(homeDir, state);
  child.unref();
  return state;
}

async function stopProcess({ homeDir = os.homedir() } = {}) {
  const state = readState(homeDir);
  if (!state) return { running: false };
  if (isAlive(state.pid)) {
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
  return running ? { ...state, running: true } : { running: false };
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
  isAlive,
  readStatus,
  startProcess,
  statePath,
  stopProcess,
};
