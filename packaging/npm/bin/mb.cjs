#!/usr/bin/env node

const fs = require('node:fs');
const net = require('node:net');
const os = require('node:os');
const path = require('node:path');
const readline = require('node:readline');
const { spawn } = require('node:child_process');
const {
  applyPortOverride,
  defaultConfig,
  loadConfig,
  saveConfig,
} = require('../lib/config.cjs');
const { parseNonInteractiveConfig, runWizard } = require('../lib/wizard.cjs');
const { openGui } = require('../lib/gui.cjs');
const { resolveRuntime } = require('../lib/runtime.cjs');
const {
  checkHealth,
  readStatus,
  removeManagedTree,
  startProcess,
  stopProcess,
} = require('../lib/process.cjs');

const configDir = path.join(os.homedir(), '.media-bridge');
const configFile = path.join(configDir, 'config.json');
const serviceFile = path.join(configDir, 'service.json');
const pidFile = path.join(configDir, 'service.pid');

function help() {
  process.stdout.write(`Media Bridge\n\nCommands:\n  media-bridge init\n  media-bridge start [--port 8765]\n  media-bridge stop\n  media-bridge status\n  media-bridge health [--json]\n  media-bridge ready [--json] [--wait] [--timeout <seconds>]\n  media-bridge gui\n  media-bridge service <install|repair|restart|start|stop|status|uninstall|remove>\n  media-bridge update\n  media-bridge uninstall [--keep-config|--delete-config]\n\nCompatibility alias: mb\n`);
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
  saveConfig({ homeDir: os.homedir(), config });
  process.stdout.write(`Media Bridge initialized: ${configFile}\n`);
}

async function start(argv) {
  let config = readConfig();
  const portIndex = argv.indexOf('--port');
  const port = portIndex >= 0 ? Number(argv[portIndex + 1]) : Number(config.port);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error('포트는 1부터 65535 사이의 정수여야 합니다.');
  }
  if (portIndex >= 0) {
    config = applyPortOverride(config, port);
    saveConfig({ homeDir: os.homedir(), config });
  }
  const runtime = await resolveRuntime({ homeDir: os.homedir() });
  const state = await startProcess({ config, runtime, homeDir: os.homedir(), portOverride: port });
  process.stdout.write(`Media Bridge started: ${state.pid}\n`);
}

function status(json) {
  const { host, port } = readConfig();
  const result = { ...readStatus({ homeDir: os.homedir() }), host, port };
  process.stdout.write(json ? `${JSON.stringify(result)}\n` : `${result.running ? 'running' : 'stopped'} ${host}:${port}\n`);
  if (!result.running) process.exitCode = 1;
}

async function health(json) {
  const config = readConfig();
  const result = await checkHealth({ config });
  process.stdout.write(json ? `${JSON.stringify(result)}\n` : `${result.healthy ? 'healthy' : 'unhealthy'} ${result.url}\n`);
  if (!result.healthy) process.exitCode = 1;
}

function gui() {
  const { host, port } = readConfig();
  const url = `http://${host}:${port}/`;
  openGui(url);
  process.stdout.write(`설정 화면 주소: ${url}\n`);
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

async function service(action) {
  if (!action || action === 'status') {
    const installed = fs.existsSync(serviceFile);
    const running = readStatus({ homeDir: os.homedir() }).running;
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
    await stopProcess({ homeDir: os.homedir() });
    process.stdout.write('service uninstalled\n');
    return;
  }
  if (action === 'start') {
    if (!fs.existsSync(serviceFile)) service('install');
    const config = readConfig();
    const runtime = await resolveRuntime({ homeDir: os.homedir() });
    const state = await startProcess({ config, runtime, homeDir: os.homedir() });
    process.stdout.write(`service started: ${state.pid}\n`);
    return;
  }
  if (action === 'stop') {
    if (!readStatus({ homeDir: os.homedir() }).running) {
      await stopProcess({ homeDir: os.homedir() });
      process.stdout.write('service already stopped\n');
      return;
    }
    await stopProcess({ homeDir: os.homedir() });
    process.stdout.write('service stopped\n');
    return;
  }
  if (action === 'restart') {
    await service('stop');
    return service('start');
  }
  throw new Error(`알 수 없는 service 명령입니다: ${action}`);
}

async function shouldDeleteConfig(argv) {
  const keepConfig = argv.includes('--keep-config');
  const deleteConfig = argv.includes('--delete-config');
  if (keepConfig && deleteConfig) {
    throw new Error('--keep-config과 --delete-config은 함께 사용할 수 없습니다.');
  }
  if (deleteConfig) return true;
  if (keepConfig || !process.stdin.isTTY || !process.stdout.isTTY) return false;

  const interfaceRef = readline.createInterface({ input: process.stdin, output: process.stdout });
  try {
    const answer = await new Promise((resolve) => {
      interfaceRef.question('Media Bridge 설정도 삭제하시겠습니까? [y/N]: ', resolve);
    });
    return /^(y|yes|예)$/i.test(answer.trim());
  } finally {
    interfaceRef.close();
  }
}

async function uninstall(argv) {
  const deleteConfig = await shouldDeleteConfig(argv);
  await service('uninstall');
  await removeManagedTree(path.join(configDir, 'runtime'));
  if (deleteConfig) {
    fs.rmSync(configFile, { force: true });
    await removeManagedTree(path.join(configDir, 'runtime-config'));
  }
  try {
    fs.rmdirSync(configDir);
  } catch (error) {
    if (error.code !== 'ENOENT' && error.code !== 'ENOTEMPTY') throw error;
  }
  process.stdout.write(`Media Bridge runtime을 제거하고 설정을 ${deleteConfig ? '삭제했습니다' : '보존했습니다'}.\n`);
  process.stdout.write('CLI 패키지 제거: npm uninstall -g @cyhuh/media-bridge\n');
}

async function main(argv) {
  const [command, ...rest] = argv;
  if (!command || command === 'help' || command === '--help' || command === '-h') return help();
  if (command === 'init') return init();
  if (command === 'start') return start(rest);
  if (command === 'stop') return service('stop');
  if (command === 'status') return status(rest.includes('--json'));
  if (command === 'health') return health(rest.includes('--json'));
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
    return uninstall(rest);
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
