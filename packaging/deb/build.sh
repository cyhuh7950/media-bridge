#!/usr/bin/env bash
set -euo pipefail

source_root=${1:?source root is required}
output=${2:?output path is required}
version=${3:-0.1.0}
test -x "$source_root/.venv/bin/python"
architecture=$(dpkg --print-architecture)
test -n "$architecture"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
pkg="$work/media-bridge-$version"
mkdir -p "$pkg/DEBIAN" "$pkg/opt/media-bridge/app" "$pkg/opt/media-bridge/runtime"
cp -aL "$source_root/.venv/." "$pkg/opt/media-bridge/runtime/"
cp -a "$source_root/media_bridge_personal" "$pkg/opt/media-bridge/app/"
cp -a "$source_root/media_bridge" "$pkg/opt/media-bridge/app/"
rm -f "$pkg/opt/media-bridge/app/media_bridge/omniroute_adapter.py"
mkdir -p "$pkg/opt/media-bridge/app/media_bridge_adapters"
cp "$source_root/media_bridge_adapters/__init__.py" "$pkg/opt/media-bridge/app/media_bridge_adapters/"
cp -a "$source_root/media_bridge_adapters/opencodex" "$pkg/opt/media-bridge/app/media_bridge_adapters/"
cp -a "$source_root/media_bridge_gateway" "$pkg/opt/media-bridge/app/"
cp "$source_root/packaging/deb/control" "$pkg/DEBIAN/control"
sed -i "s/^Version: .*/Version: $version/" "$pkg/DEBIAN/control"
sed -i "s/^Architecture: .*/Architecture: $architecture/" "$pkg/DEBIAN/control"
mkdir -p "$pkg/usr/bin" "$pkg/usr/lib/systemd/user"
cp "$source_root/packaging/deb/media-bridge-personal-web" "$pkg/usr/bin/media-bridge-personal-web"
chmod 0755 "$pkg/usr/bin/media-bridge-personal-web"
cp "$source_root/packaging/deb/media-bridge-personal-data" "$pkg/usr/bin/media-bridge-personal-data"
chmod 0755 "$pkg/usr/bin/media-bridge-personal-data"
cp "$source_root/packaging/deb/media-bridge-web.service" "$pkg/usr/lib/systemd/user/media-bridge-web.service"
cp "$source_root/packaging/deb/media-bridge-data.service" "$pkg/usr/lib/systemd/user/media-bridge-data.service"
mkdir -p "$(dirname "$output")"
# The source venv is an editable development environment; never ship its
# source-tree pointers or project install metadata in the product runtime.
find "$pkg/opt/media-bridge/runtime" -type f \( -name '__editable__*.pth' -o -name '__editable__*_finder.py' -o -name '*.egg-link' \) -delete
find "$pkg/opt/media-bridge/runtime" -type d -name 'nonvision_media_bridge-*.dist-info' -prune -exec rm -rf {} +
find "$pkg" -type d -name __pycache__ -prune -exec rm -rf {} +
dpkg-deb --build --root-owner-group "$pkg" "$output"
