#!/usr/bin/env bash
set -euo pipefail

python_path=''
version=''
output_dir=''
work_dir=''
base_url=''

while [[ $# -gt 0 ]]; do
  case "$1" in
    --python) python_path="${2:-}"; shift 2 ;;
    --version) version="${2:-}"; shift 2 ;;
    --output-dir) output_dir="${2:-}"; shift 2 ;;
    --work-dir) work_dir="${2:-}"; shift 2 ;;
    --base-url) base_url="${2:-}"; shift 2 ;;
    *) printf 'Unknown argument: %s\n' "$1" >&2; exit 2 ;;
  esac
done

[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { printf 'Version must use x.y.z format.\n' >&2; exit 2; }
[[ "$output_dir" = /* ]] || { printf 'OutputDirectory must be an absolute path.\n' >&2; exit 2; }
[[ "$work_dir" = /* ]] || { printf 'WorkDirectory must be an absolute path.\n' >&2; exit 2; }
[[ -x "$python_path" ]] || { printf 'Python executable is unavailable: %s\n' "$python_path" >&2; exit 2; }

"$python_path" - "$base_url" <<'PY'
import sys
from urllib.parse import urlparse

parsed = urlparse(sys.argv[1])
allowed = parsed.scheme == "https" or (
    parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
)
if not allowed:
    raise SystemExit("BaseUrl must use HTTPS or loopback HTTP.")
PY
"$python_path" - <<'PY'
import pathlib
import platform
import struct
import sys

if platform.system() != "Linux" or platform.machine().lower() not in {"aarch64", "arm64"} or struct.calcsize("P") != 8:
    raise SystemExit("linux-arm64 runtime requires 64-bit Linux ARM64 Python.")
if (pathlib.Path(sys.base_prefix) / "conda-meta").is_dir():
    raise SystemExit("linux-arm64 runtime builds require official CPython; Conda distributions are unsupported.")
PY

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
source_root="$(cd "$script_dir/../.." && pwd -P)"
pyinstaller_dist="$work_dir/pyinstaller-dist"
pyinstaller_work="$work_dir/pyinstaller-work"
pyinstaller_spec="$work_dir/pyinstaller-spec"
payload_dir="$work_dir/payload"
entrypoint="$script_dir/entrypoint.py"

rm -rf -- "$pyinstaller_dist" "$pyinstaller_work" "$pyinstaller_spec" "$payload_dir"
mkdir -p -- "$output_dir" "$work_dir"

cd "$work_dir"
"$python_path" -m PyInstaller \
  --noconfirm \
  --clean \
  --onedir \
  --name media-bridge-runtime \
  --paths "$source_root" \
  --distpath "$pyinstaller_dist" \
  --workpath "$pyinstaller_work" \
  --specpath "$pyinstaller_spec" \
  "$entrypoint"

built_root="$pyinstaller_dist/media-bridge-runtime"
built_executable="$built_root/media-bridge-runtime"
[[ -x "$built_executable" ]] || { printf 'PyInstaller output executable is missing or not executable.\n' >&2; exit 1; }

mkdir -p -- "$payload_dir/bin"
cp -a -- "$built_root/." "$payload_dir/bin/"

artifact_name="media-bridge-runtime-$version-linux-arm64.tar.gz"
artifact_path="$output_dir/$artifact_name"
checksum_path="$artifact_path.sha256"
manifest_path="$output_dir/runtime-manifest.json"
rm -f -- "$artifact_path" "$checksum_path" "$manifest_path"
tar -czf "$artifact_path" -C "$payload_dir" .
sha256="$(sha256sum "$artifact_path" | awk '{print $1}')"
printf '%s  %s\n' "$sha256" "$artifact_name" > "$checksum_path"
artifact_url="${base_url%/}/$artifact_name"

"$python_path" - "$manifest_path" "$version" "$artifact_url" "$sha256" <<'PY'
import json
import pathlib
import sys

manifest_path, version, url, sha256 = sys.argv[1:]
manifest = {
    "schemaVersion": 1,
    "packageVersion": version,
    "artifacts": {
        "linux-arm64": {
            "version": version,
            "published": True,
            "url": url,
            "sha256": sha256,
            "archive": "tar.gz",
            "command": "bin/media-bridge-runtime",
            "python": False,
        }
    },
}
pathlib.Path(manifest_path).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
PY

"$python_path" - "$artifact_path" "$checksum_path" "$manifest_path" "$sha256" <<'PY'
import json
import pathlib
import sys

artifact, checksum, manifest, sha256 = sys.argv[1:]
print(json.dumps({
    "artifact": artifact,
    "checksum": checksum,
    "manifest": manifest,
    "sha256": sha256,
    "bytes": pathlib.Path(artifact).stat().st_size,
}, separators=(",", ":")))
PY
