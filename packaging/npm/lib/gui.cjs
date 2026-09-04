const { spawn } = require('node:child_process');

function openGui(url, {
  platform = process.platform,
  env = process.env,
  spawnImpl = spawn,
} = {}) {
  let command;
  if (platform === 'win32') command = 'explorer.exe';
  else if (platform === 'darwin') command = 'open';
  else if (platform === 'linux' && (env.DISPLAY || env.WAYLAND_DISPLAY)) command = 'xdg-open';
  else return false;

  const child = spawnImpl(command, [url], {
    detached: true,
    stdio: 'ignore',
    windowsHide: true,
  });
  child.on('error', () => {});
  child.unref();
  return true;
}

module.exports = { openGui };
