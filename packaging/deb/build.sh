#!/usr/bin/env bash
set -euo pipefail

source_root=${1:?source root is required}
output=${2:?output path is required}
version=${3:-0.1.0}
test -x "$source_root/.venv/bin/python"
architecture=$(dpkg --print-architecture)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
pkg="$work/media-bridge-$version"

mkdir -p "$pkg/DEBIAN" "$pkg/opt/media-bridge/app" "$pkg/opt/media-bridge/runtime/bin"
cp -aL "$source_root/.venv/." "$pkg/opt/media-bridge/runtime/"
cp -a "$source_root/media_bridge" "$pkg/opt/media-bridge/app/"
cp -a "$source_root/media_bridge_adapters" "$pkg/opt/media-bridge/app/"
cp -a "$source_root/media_bridge_gateway" "$pkg/opt/media-bridge/app/"
cp -a "$source_root/media_bridge_control" "$pkg/opt/media-bridge/app/"
cp "$source_root/packaging/deb/control" "$pkg/DEBIAN/control"
sed -i "s/^Version: .*/Version: $version/" "$pkg/DEBIAN/control"
sed -i "s/^Architecture: .*/Architecture: $architecture/" "$pkg/DEBIAN/control"

cp "$source_root/packaging/deb/media-bridge-http" "$pkg/opt/media-bridge/runtime/bin/media-bridge-http"
chmod 0755 "$pkg/opt/media-bridge/runtime/bin/media-bridge-http"

# The source virtual environment is editable; do not ship source-tree pointers.
find "$pkg/opt/media-bridge/runtime" -type f \( -name '__editable__*.pth' -o -name '__editable__*_finder.py' -o -name '*.egg-link' \) -delete
find "$pkg/opt/media-bridge/runtime" -type d -name 'nonvision_media_bridge-*.dist-info' -prune -exec rm -rf {} +
find "$pkg" -type d -name __pycache__ -prune -exec rm -rf {} +
mkdir -p "$(dirname "$output")"
dpkg-deb --build --root-owner-group "$pkg" "$output"
