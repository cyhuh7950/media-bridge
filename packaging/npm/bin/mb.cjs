#!/usr/bin/env node

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const readline = require('node:readline');
const { execFileSync, spawn } = require('node:child_process');
const {
  applyHostOverride,
  applyPortOverride,
  defaultConfig,
  loadConfig,
  saveConfig,
} = require('../lib/config.cjs');
const { parseNonInteractiveConfig, runWizard } = require('../lib/wizard.cjs');
const { openGui } = require('../lib/gui.cjs');
const { resolveRuntime } = require('../lib/runtime.cjs');
const {
  checkManagedHealth,
  readStatus,
  removeManagedTree,
  startManagedRuntime,
  stopProcess,
} = require('../lib/process.cjs');

const configDir = path.join(os.homedir(), '.media-bridge');
const configFile = path.join(configDir, 'config.json');
const serviceFile = path.join(configDir, 'service.json');
const pidFile = path.join(configDir, 'service.pid');

function help() {
  process.stdout.write(`Media Bridge\n\nCommands:\n  media-bridge init [--host HOST] [--port PORT]\n  media-bridge start [--port 8642]\n  media-bridge stop\n  media-bridge status\n  media-bridge health [--json]\n  media-bridge ready [--json] [--wait] [--timeout <seconds>]\n  media-bridge gui\n  media-bridge service <install|repair|restart|start|stop|status|uninstall|remove>\n  media-bridge update\n  media-bridge uninstall [--keep-config|--delete-config]\n\nCompatibility alias: mb\n`);
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

function cliPath() {
  return path.resolve(process.argv[1]);
}

function runQuiet(command, args) {
  try {
    execFileSync(command, args, { stdio: 'ignore', windowsHide: true });
    return true;
  } catch {
    return false;
  }
}

function systemdUnitPath(homeDir = os.homedir()) {
  return path.join(homeDir, '.config', 'systemd', 'user', 'media-bridge.service');
}

function profilePath(homeDir = os.homedir()) {
  return path.join(homeDir, '.profile');
}

function windowsStartupPath(homeDir = os.homedir()) {
  const appData = path.join(homeDir, 'AppData', 'Roaming');
  return path.join(appData, 'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Startup', 'Media Bridge.cmd');
}

function profileBlock() {
  return [
    '# >>> media-bridge autostart >>>',
    `if command -v node >/dev/null 2>&1; then nohup node ${shellQuote(cliPath())} service start >/dev/null 2>&1 & fi`,
    '# <<< media-bridge autostart <<<',
  ].join('\n');
}

function shellQuote(value) {
  return `'${String(value).replace(/'/g, "'\\''")}'`;
}

function installProfileAutostart(homeDir = os.homedir()) {
  const target = profilePath(homeDir);
  const existing = fs.existsSync(target) ? fs.readFileSync(target, 'utf8') : '';
  const block = profileBlock();
  if (!existing.includes('# >>> media-bridge autostart >>>')) {
    fs.mkdirSync(path.dirname(target), { recursive: true, mode: 0o700 });
    fs.writeFileSync(target, `${existing.replace(/\\s*$/, '')}\n\n${block}\n`, { mode: 0o600 });
  }
  return { backend: 'profile', path: target };
}

function removeProfileAutostart(homeDir = os.homedir()) {
  const target = profilePath(homeDir);
  if (!fs.existsSync(target)) return;
  const existing = fs.readFileSync(target, 'utf8');
  const cleaned = existing.replace(/\n?# >>> media-bridge autostart >>>[\s\S]*?# <<< media-bridge autostart <<<\n?/g, '\n');
  fs.writeFileSync(target, cleaned.replace(/\n{3,}/g, '\n\n'), { mode: 0o600 });
}

function installAutostart(homeDir = os.homedir()) {
  if (process.platform === 'linux') {
    const unit = systemdUnitPath(homeDir);
    const contents = `[Unit]\nDescription=Media Bridge personal runtime\nAfter=network-online.target\n\n[Service]\nType=oneshot\nExecStart=${process.execPath} ${cliPath()} service start\nRemainAfterExit=yes\n\n[Install]\nWantedBy=default.target\n`;
    fs.mkdirSync(path.dirname(unit), { recursive: true, mode: 0o700 });
    fs.writeFileSync(unit, contents, { mode: 0o600 });
    if (runQuiet('systemctl', ['--user', 'daemon-reload']) && runQuiet('systemctl', ['--user', 'enable', 'media-bridge.service'])) {
      return { backend: 'systemd-user', path: unit };
    }
    return installProfileAutostart(homeDir);
  }
  if (process.platform === 'win32') {
    const task = 'Media Bridge';
    const created = runQuiet('schtasks.exe', ['/Create', '/TN', task, '/SC', 'ONLOGON', '/F', '/TR', `"${process.execPath}" "${cliPath()}" service start`]);
    if (created) return { backend: 'task-scheduler', task };
    const startup = windowsStartupPath(homeDir);
    fs.mkdirSync(path.dirname(startup), { recursive: true });
    fs.writeFileSync(startup, `@echo off\r\n"${process.execPath}" "${cliPath()}" service start\r\n`, { mode: 0o600 });
    return { backend: 'windows-startup', path: startup };
  }
  return installProfileAutostart(homeDir);
}

function removeAutostart(homeDir = os.homedir()) {
  if (process.platform === 'linux') {
    const unit = systemdUnitPath(homeDir);
    runQuiet('systemctl', ['--user', 'disable', '--now', 'media-bridge.service']);
    if (fs.existsSync(unit)) fs.rmSync(unit);
    removeProfileAutostart(homeDir);
    return;
  }
  if (process.platform === 'win32') {
    runQuiet('schtasks.exe', ['/Delete', '/TN', 'Media Bridge', '/F']);
    const startup = windowsStartupPath(homeDir);
    if (fs.existsSync(startup)) fs.rmSync(startup);
  }
  removeProfileAutostart(homeDir);
}

function ensureAutostart(homeDir = os.homedir()) {
  let current = null;
  if (fs.existsSync(serviceFile)) {
    try { current = JSON.parse(fs.readFileSync(serviceFile, 'utf8')); } catch { current = null; }
  }
  if (current?.enabled === true) return current;
  const autostart = installAutostart(homeDir);
  fs.mkdirSync(configDir, { recursive: true, mode: 0o700 });
  const next = { version: 2, enabled: true, ...autostart };
  fs.writeFileSync(serviceFile, `${JSON.stringify(next, null, 2)}\n`, { mode: 0o600 });
  return next;
}

async function init(argv = []) {
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
  const hostIndex = argv.indexOf('--host');
  if (hostIndex >= 0) {
    const host = argv[hostIndex + 1];
    if (!host) throw new Error('--host 다음에 주소가 필요합니다.');
    config = applyHostOverride(config, host);
  }
  const portIndex = argv.indexOf('--port');
  if (portIndex >= 0) {
    const port = Number(argv[portIndex + 1]);
    if (!Number.isInteger(port)) throw new Error('--port 다음에 정수가 필요합니다.');
    config = applyPortOverride(config, port);
  }
  saveConfig({ homeDir: os.homedir(), config });
  const service = installAutostart(os.homedir());
  fs.mkdirSync(configDir, { recursive: true, mode: 0o700 });
  fs.writeFileSync(serviceFile, `${JSON.stringify({ version: 2, enabled: true, ...service }, null, 2)}\n`, { mode: 0o600 });
  process.stdout.write(`Media Bridge initialized: ${configFile}\n`);
  process.stdout.write(`자동 시작 등록: ${service.backend}\n`);
}

async function start(argv) {
  let config = readConfig();
  const portIndex = argv.indexOf('--port');
  const port = portIndex >= 0 ? Number(argv[portIndex + 1]) : Number(config.port);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error('포트는 1부터 65535 사이의 정수여야 합니다.');
  }
  const current = readStatus({ homeDir: os.homedir() });
  if (current.running) throw new Error(`Media Bridge is already running: ${current.pid}`);
  ensureAutostart(os.homedir());
  if (portIndex >= 0) {
    config = applyPortOverride(config, port);
    saveConfig({ homeDir: os.homedir(), config });
  }
  const state = await startManagedRuntime({
    config,
    homeDir: os.homedir(),
    portOverride: port,
    resolveRuntimeImpl: resolveRuntime,
  });
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
  const result = await checkManagedHealth({ config, homeDir: os.homedir() });
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
  const check = async () => {
    const { host, port } = readConfig();
    const result = await checkManagedHealth({
      config: { host, port },
      homeDir: os.homedir(),
    });
    if (result.healthy) {
      process.stdout.write(json ? `${JSON.stringify({ ready: true, host, port })}\n` : `ready ${host}:${port}\n`);
      return;
    }
    if (wait && Date.now() < deadline) return setTimeout(check, 100);
    process.stdout.write(json ? `${JSON.stringify({ ready: false, host, port })}\n` : `not-ready ${host}:${port}\n`);
    process.exitCode = 1;
  };
  return check();
}

async function service(action) {
  if (!action || action === 'status') {
    const installed = fs.existsSync(serviceFile);
    const running = readStatus({ homeDir: os.homedir() }).running;
    process.stdout.write(`${installed ? 'installed' : 'not-installed'} ${running ? 'running' : 'stopped'}\n`);
    return;
  }
  if (action === 'install') {
    const autostart = installAutostart(os.homedir());
    fs.mkdirSync(configDir, { recursive: true, mode: 0o700 });
    fs.writeFileSync(serviceFile, `${JSON.stringify({ version: 2, enabled: true, ...autostart }, null, 2)}\n`, {
      mode: 0o600,
    });
    process.stdout.write(`service installed: ${autostart.backend}\n`);
    return;
  }
  if (action === 'uninstall') {
    removeAutostart(os.homedir());
    if (fs.existsSync(serviceFile)) fs.rmSync(serviceFile);
    await stopProcess({ homeDir: os.homedir() });
    process.stdout.write('service uninstalled\n');
    return;
  }
  if (action === 'start') {
    if (!fs.existsSync(serviceFile)) service('install');
    const config = readConfig();
    const state = await startManagedRuntime({
      config,
      homeDir: os.homedir(),
      resolveRuntimeImpl: resolveRuntime,
    });
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
  if (command === 'init') return init(rest);
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
