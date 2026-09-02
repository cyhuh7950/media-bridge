const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '../..');
const read = (file) => fs.readFileSync(path.join(root, file), 'utf8');

test('user-facing docs use the approved npm package and lifecycle surface', () => {
  const files = [
    'README.md',
    'packaging/npm/README.md',
    'docs/manuals/user/getting-started.md',
    'docs/manuals/user/npm-cli.md',
    'docs/install/linux.md',
  ];
  for (const file of files) {
    const content = read(file);
    assert.match(content, /@bitkyc08\/media-bridge/, file);
    assert.doesNotMatch(content, /@cyhuh\/media-bridge/, file);
  }
  const linux = read('docs/install/linux.md');
  for (const command of [
    'mb init', 'mb start', 'mb stop', 'mb status', 'mb health', 'mb gui',
    'mb service install', 'mb service start', 'mb service stop',
    'mb service restart', 'mb service uninstall', 'mb update',
  ]) assert.match(linux, new RegExp(command.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  assert.match(linux, /\.deb.*내부|내부.*\.deb|operator|복구/i);
});

test('getting started does not instruct general users to run legacy dpkg or systemctl', () => {
  const content = read('docs/manuals/user/getting-started.md');
  assert.doesNotMatch(content, /sudo dpkg|systemctl --user/);
});
