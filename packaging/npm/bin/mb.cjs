#!/usr/bin/env node

const fs = require('node:fs');
const net = require('node:net');
const os = require('node:os');
const path = require('node:path');
const readline = require('node:readline');
const { spawn } = require('node:child_process');
const { defaultConfig, loadConfig, saveConfig } = require('../lib/config.cjs');
const { parseNonInteractiveConfig, runWizard } = require('../lib/wizard.cjs');

const configDir = path.join(os.homedir(), '.media-bridge');
const configFile = path.join(configDir, 'config.json');
const serviceFile = path.join(configDir, 'service.json');
const pidFile = path.join(configDir, 'service.pid');

function help() {
  process.stdout.write(`Media Bridge\n\nCommands:\n  media-bridge init\n  media-bridge start [--port 8765]\n  media-bridge stop\n  media-bridge status\n  media-bridge health [--json]\n  media-bridge ready [--json] [--wait] [--timeout <seconds>]\n  media-bridge gui\n  media-bridge service <install|repair|restart|start|stop|status|uninstall|remove>\n  media-bridge update\n  media-bridge uninstall\n\nCompatibility alias: mb\n`);
}

function detectExecutable(names) {
  const pathEntries = (process.env.PATH || '').split(path.delimiter).filter(Boolean);
  const extensions = process.platform === 'win32' ? ['', '.cmd', '.exe'] : [''];
  for (const name of names) {
    for (const entry of pathEntries) {
      for (const extension of extensions) {
        const candidate = path.join(entry, `${name}${extension}`);
        if (fs.existsSync(candidate)) return candidate;
      }
    }
  }
  return null;
}

function readConfig() {
  return loadConfig({ homeDir: os.homedir() });
}

async function init() {
  const existing = fs.existsSync(configFile) ? readConfig() : defaultConfig();
  let config;
  if (process.stdin.isTTY && process.stdout.isTTY) {
    const interfaceRef = readline.createInterface({ input: process.stdin, output: process.stdout });
    try {
      config = await runWizard({
        existingConfig: existing,
        ask: (question, fallback) => new Promise((resolve) => {
          interfaceRef.question(`${question} [${fallback}]: `, resolve);
        }),
      });
    } finally {
      interfaceRef.close();
    }
  } else {
    config = parseNonInteractiveConfig(process.env, existing);
  }
  if (!config.openCodex) {
    config.openCodex = { detectedCommand: detectExecutable(['opencodex', 'ocx']) };
  }
  saveConfig({ homeDir: os.homedir(), config });
  process.stdout.write(`Media Bridge initialized: ${configFile}\n`);
}

function pythonCommand() {
  if (process.env.MEDIA_BRIDGE_PYTHON) return process.env.MEDIA_BRIDGE_PYTHON;
  if (process.platform !== 'win32' && fs.existsSync('/opt/media-bridge/runtime/bin/python')) {
    return '/opt/media-bridge/runtime/bin/python';
  }
  return process.platform === 'win32' ? 'python' : 'python3';
}

function pythonEnvironment() {
  const env = { ...process.env };
  if (process.platform !== 'win32' && fs.existsSync('/opt/media-bridge/app')) {
    env.PYTHONPATH = env.PYTHONPATH
      ? `/opt/media-bridge/app${path.delimiter}${env.PYTHONPATH}`
      : '/opt/media-bridge/app';
  }
  return env;
}

function start(argv) {
  const config = readConfig();
  const portIndex = argv.indexOf('--port');
  const port = portIndex >= 0 ? Number(argv[portIndex + 1]) : Number(config.port);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error('포트는 1부터 65535 사이의 정수여야 합니다.');
  }
  const child = spawn(pythonCommand(), ['-c', 'from media_bridge.entrypoints import run_http; run_http()'], {
    stdio: 'inherit',
    env: {
      ...pythonEnvironment(),
      MEDIA_BRIDGE_HTTP_HOST: config.host,
      MEDIA_BRIDGE_HTTP_PORT: String(port),
    },
  });
  child.on('error', (error) => {
    process.stderr.write(`Media Bridge 실행기를 시작하지 못했습니다: ${error.message}\n`);
    process.exitCode = 1;
  });
  child.on('exit', (code, signal) => {
    process.exitCode = code ?? 1;
    if (signal) process.stderr.write(`Media Bridge가 ${signal}로 종료되었습니다.\n`);
  });
}

function status(json) {
  const { host, port } = readConfig();
  const socket = net.createConnection({ host, port });
  socket.once('connect', () => {
    socket.destroy();
    const result = { running: true, host, port };
    process.stdout.write(json ? `${JSON.stringify(result)}\n` : `running ${host}:${port}\n`);
  });
  socket.once('error', () => {
    const result = { running: false, host, port };
    process.stdout.write(json ? `${JSON.stringify(result)}\n` : `stopped ${host}:${port}\n`);
    process.exitCode = 1;
  });
}

function gui() {
  const { host, port } = readConfig();
  process.stdout.write(`설정 화면 주소: http://${host}:${port}/\n`);
}

function ready(argv) {
  const wait = argv.includes('--wait');
  const json = argv.includes('--json');
  const timeoutIndex = argv.indexOf('--timeout');
  const timeout = timeoutIndex >= 0 ? Number(argv[timeoutIndex + 1]) : 0;
  const deadline = Date.now() + (Number.isFinite(timeout) && timeout > 0 ? timeout * 1000 : 0);
  const check = () => {
    const { host, port } = readConfig();
    const socket = net.createConnection({ host, port });
    socket.once('connect', () => {
      socket.destroy();
      process.stdout.write(json ? `${JSON.stringify({ ready: true, host, port })}\n` : `ready ${host}:${port}\n`);
    });
    socket.once('error', () => {
      socket.destroy();
      if (wait && Date.now() < deadline) return setTimeout(check, 100);
      process.stdout.write(json ? `${JSON.stringify({ ready: false, host, port })}\n` : `not-ready ${host}:${port}\n`);
      process.exitCode = 1;
    });
  };
  check();
}

function service(action) {
  if (!action || action === 'status') {
    const installed = fs.existsSync(serviceFile);
    let running = false;
    if (fs.existsSync(pidFile)) {
      const pid = Number(fs.readFileSync(pidFile, 'utf8'));
      try {
        process.kill(pid, 0);
        running = Number.isInteger(pid) && pid > 0;
      } catch {
        fs.rmSync(pidFile);
      }
    }
    process.stdout.write(`${installed ? 'installed' : 'not-installed'} ${running ? 'running' : 'stopped'}\n`);
    return;
  }
  if (action === 'install') {
    fs.mkdirSync(configDir, { recursive: true, mode: 0o700 });
    fs.writeFileSync(serviceFile, `${JSON.stringify({ version: 1, enabled: false }, null, 2)}\n`, {
      mode: 0o600,
    });
    process.stdout.write(`service installed: ${serviceFile}\n`);
    return;
  }
  if (action === 'uninstall') {
    if (fs.existsSync(serviceFile)) fs.rmSync(serviceFile);
    if (fs.existsSync(pidFile)) fs.rmSync(pidFile);
    process.stdout.write('service uninstalled\n');
    return;
  }
  if (action === 'start') {
    if (!fs.existsSync(serviceFile)) service('install');
    if (fs.existsSync(pidFile)) {
      process.stdout.write('service already started or stale pid exists; run status first\n');
      return;
    }
    const config = readConfig();
    const child = spawn(pythonCommand(), ['-c', 'from media_bridge.entrypoints import run_http; run_http()'], {
      detached: true,
      stdio: 'ignore',
      env: {
        ...pythonEnvironment(),
        MEDIA_BRIDGE_HTTP_HOST: config.host,
        MEDIA_BRIDGE_HTTP_PORT: String(config.port),
      },
    });
    fs.mkdirSync(configDir, { recursive: true, mode: 0o700 });
    fs.writeFileSync(pidFile, `${child.pid}\n`, { mode: 0o600 });
    child.unref();
    process.stdout.write(`service started: ${child.pid}\n`);
    return;
  }
  if (action === 'stop') {
    if (!fs.existsSync(pidFile)) {
      process.stdout.write('service already stopped\n');
      return;
    }
    const pid = Number(fs.readFileSync(pidFile, 'utf8'));
    try { process.kill(pid); } catch { /* process already exited */ }
    fs.rmSync(pidFile);
    process.stdout.write('service stopped\n');
    return;
  }
  if (action === 'restart') {
    service('stop');
    return service('start');
  }
  throw new Error(`알 수 없는 service 명령입니다: ${action}`);
}

async function main(argv) {
  const [command, ...rest] = argv;
  if (!command || command === 'help' || command === '--help' || command === '-h') return help();
  if (command === 'init') return init();
  if (command === 'start') return start(rest);
  if (command === 'stop') return service('stop');
  if (command === 'status' || command === 'health') return status(rest.includes('--json'));
  if (command === 'ready') return ready(rest);
  if (command === 'gui') return gui();
  if (command === 'service') {
    if (rest[0] === 'repair' || rest[0] === 'remove') return service(rest[0] === 'repair' ? 'install' : 'uninstall');
    return service(rest[0]);
  }
  if (command === 'update') {
    process.stdout.write('npm update -g @cyhuh/media-bridge 를 실행하십시오.\n');
    return;
  }
  if (command === 'uninstall') {
    service('stop');
    if (fs.existsSync(configDir)) fs.rmSync(configDir, { recursive: true });
    process.stdout.write('Media Bridge uninstalled\n');
    return;
  }
  throw new Error(`알 수 없는 명령입니다: ${command}`);
}

try {
  Promise.resolve(main(process.argv.slice(2))).catch((error) => {
    process.stderr.write(`${error.message}\n`);
    process.exitCode = 1;
  });
} catch (error) {
  process.stderr.write(`${error.message}\n`);
  process.exitCode = 1;
}
