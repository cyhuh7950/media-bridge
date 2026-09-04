#!/usr/bin/env bash
set -euo pipefail

artifact_dir=''
test_root=''
source_commit=''
port='0'

while [[ $# -gt 0 ]]; do
  case "$1" in
    --artifact-dir) artifact_dir="${2:-}"; shift 2 ;;
    --test-root) test_root="${2:-}"; shift 2 ;;
    --source-commit) source_commit="${2:-}"; shift 2 ;;
    --port) port="${2:-}"; shift 2 ;;
    *) printf 'Unknown argument: %s\n' "$1" >&2; exit 2 ;;
  esac
done

[[ "$artifact_dir" = /* ]] || { printf 'ArtifactDirectory must be an absolute path.\n' >&2; exit 2; }
[[ "$test_root" = /* ]] || { printf 'TestRoot must be an absolute path.\n' >&2; exit 2; }
[[ "$source_commit" =~ ^[0-9a-fA-F]{7,64}$ ]] || { printf 'SourceCommit must be a hexadecimal Git commit identifier.\n' >&2; exit 2; }
[[ "$port" =~ ^[0-9]+$ ]] && (( port >= 0 && port <= 65535 )) || { printf 'Port must be 0 or a valid TCP port.\n' >&2; exit 2; }
[[ "$(uname -s)" = Linux && "$(uname -m)" =~ ^(aarch64|arm64)$ ]] || { printf 'linux-arm64 verification requires 64-bit Linux ARM64.\n' >&2; exit 2; }
[[ -d "$artifact_dir" ]] || { printf 'ArtifactDirectory does not exist: %s\n' "$artifact_dir" >&2; exit 2; }
[[ ! -e "$test_root" ]] || { printf 'TestRoot must not already exist: %s\n' "$test_root" >&2; exit 2; }

shopt -s nullglob
artifacts=("$artifact_dir"/media-bridge-runtime-*-linux-arm64.tar.gz)
(( ${#artifacts[@]} == 1 )) || { printf 'ArtifactDirectory must contain exactly one linux-arm64 runtime archive.\n' >&2; exit 2; }
artifact="${artifacts[0]}"
artifact_name="$(basename "$artifact")"
checksum_path="$artifact.sha256"
manifest_path="$artifact_dir/runtime-manifest.json"
[[ -f "$checksum_path" ]] || { printf 'Checksum file is missing: %s\n' "$checksum_path" >&2; exit 2; }
[[ -f "$manifest_path" ]] || { printf 'Runtime manifest is missing: %s\n' "$manifest_path" >&2; exit 2; }

read -r expected_sha checksum_name < "$checksum_path"
[[ "$expected_sha" =~ ^[0-9a-fA-F]{64}$ && "$checksum_name" = "$artifact_name" ]] || {
  printf 'Checksum file must contain SHA-256 and the artifact filename.\n' >&2; exit 2;
}
actual_sha="$(sha256sum "$artifact" | awk '{print $1}')"
[[ "${expected_sha,,}" = "$actual_sha" ]] || { printf 'Runtime archive SHA-256 does not match its checksum file.\n' >&2; exit 2; }

node - "$manifest_path" "$actual_sha" <<'NODE'
const fs = require('node:fs');
const [manifestPath, actualSha] = process.argv.slice(2);
const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
const entry = manifest.artifacts?.['linux-arm64'];
if (manifest.schemaVersion !== 1 || !entry) throw new Error('Runtime manifest does not contain schema 1 linux-arm64 metadata.');
if (!entry.published || entry.sha256 !== actualSha) throw new Error('Runtime manifest publication state or SHA-256 does not match the archive.');
if (entry.archive !== 'tar.gz' || entry.command !== 'bin/media-bridge-runtime' || entry.python !== false) {
  throw new Error('Runtime manifest command contract is invalid.');
}
NODE

runtime_pid=''
cleanup() {
  if [[ -n "$runtime_pid" ]] && kill -0 "$runtime_pid" 2>/dev/null; then
    kill "$runtime_pid" 2>/dev/null || true
    wait "$runtime_pid" 2>/dev/null || true
  fi
  rm -rf -- "$test_root"
}
trap cleanup EXIT

mkdir -p -- "$test_root/extracted" "$test_root/assets" "$test_root/no-python-path"
inventory_path="$test_root/inventory.txt"
tar -tzf "$artifact" | sed -e 's#^\./##' > "$inventory_path"
if grep -Eiq '(^|/)(tests?|credentials?|secrets?)(/|$)|(^|/)\.env($|\.)|(^|/)config\.json$|\.py$' "$inventory_path"; then
  printf 'Runtime archive contains forbidden entries.\n' >&2
  exit 1
fi
grep -Fxq 'bin/media-bridge-runtime' "$inventory_path" || { printf 'Runtime archive does not contain the manifest command.\n' >&2; exit 1; }
tar -xzf "$artifact" -C "$test_root/extracted"
runtime_command="$test_root/extracted/bin/media-bridge-runtime"
[[ -x "$runtime_command" ]] || { printf 'Extracted runtime command is missing or not executable.\n' >&2; exit 1; }

if (( port == 0 )); then
  port="$(node -e "const n=require('node:net');const s=n.createServer();s.listen(0,'127.0.0.1',()=>{console.log(s.address().port);s.close()})")"
fi
registry_path="$test_root/model-registry.yaml"
config_path="$test_root/config.json"
printf '%s\n' \
  'version: "external-retest"' \
  'models:' \
  '  - id: solar-pro4' \
  '    input_modalities: [text]' \
  '    expires_at: 2099-01-01T00:00:00Z' \
  '    pdf_passthrough_verified: false' > "$registry_path"
cat > "$config_path" <<JSON
{
  "runtimeMode": "personal",
  "host": "127.0.0.1",
  "port": $port,
  "opencodex": {"baseUrl": "http://127.0.0.1:$port/v1"},
  "solar": {
    "model": "solar-pro4",
    "endpoint": "https://127.0.0.1:9/v1/chat/completions",
    "apiKeyEnv": "SOLAR_API_KEY"
  },
  "ocr": {
    "model": "document-parse",
    "endpoint": "https://127.0.0.1:9/v1/document-digitization",
    "apiKeyEnv": "SOLAR_API_KEY"
  },
  "conversion": {"maxBytes": 8388608, "ocrEnabled": true, "visionEnabled": true},
  "failurePolicy": {"blockSolarOnPreparationFailure": true}
}
JSON
chmod 600 "$config_path"

env -i \
  PATH="$test_root/no-python-path" \
  MEDIA_BRIDGE_CONFIG_FILE="$config_path" \
  MEDIA_BRIDGE_MODEL_REGISTRY="$registry_path" \
  MEDIA_BRIDGE_ASSET_ROOT="$test_root/assets" \
  MEDIA_BRIDGE_RECEIPT_SECRET='external-retest-receipt-secret-0001' \
  MEDIA_BRIDGE_SERVICE_TOKEN='external-retest-service-token-0001' \
  MEDIA_BRIDGE_RUNTIME_MODE='personal' \
  MEDIA_BRIDGE_SOLAR_MODEL='solar-pro4' \
  MEDIA_BRIDGE_SOLAR_ENDPOINT='https://127.0.0.1:9/v1/chat/completions' \
  MEDIA_BRIDGE_SOLAR_CREDENTIAL_ENV='SOLAR_API_KEY' \
  MEDIA_BRIDGE_OCR_ENDPOINT='https://127.0.0.1:9/v1/document-digitization' \
  MEDIA_BRIDGE_OCR_CREDENTIAL_ENV='SOLAR_API_KEY' \
  SOLAR_API_KEY='external-retest-provider-key-0001' \
  MEDIA_BRIDGE_MAX_REQUEST_BYTES='8388608' \
  MEDIA_BRIDGE_HTTP_HOST='127.0.0.1' \
  MEDIA_BRIDGE_HTTP_PORT="$port" \
  "$runtime_command" >"$test_root/runtime.stdout" 2>"$test_root/runtime.stderr" &
runtime_pid=$!

health_status=''
health_body=''
for _ in $(seq 1 120); do
  if ! kill -0 "$runtime_pid" 2>/dev/null; then
    printf 'Runtime exited before health succeeded.\n' >&2
    sed -n '1,120p' "$test_root/runtime.stderr" >&2
    exit 1
  fi
  health_body="$(curl -fsS "http://127.0.0.1:$port/health" 2>/dev/null)" && { health_status=200; break; }
  sleep 0.25
done
[[ "$health_status" = 200 ]] || { printf 'Runtime /health did not return HTTP 200 within 30 seconds.\n' >&2; exit 1; }

managed_json="$(node "$(dirname "$0")/verify-managed-runtime.cjs" "$artifact_dir" "$test_root/managed-runtime")"
node - "$managed_json" <<'NODE'
const result = JSON.parse(process.argv[2]);
if (!result.managedInstall || result.managedPython !== false || !result.checksumMismatchRejected || !result.rollbackPreserved) {
  throw new Error('Managed runtime verification result is incomplete.');
}
NODE

inventory_entries="$(wc -l < "$inventory_path" | tr -d ' ')"
node - "$artifact_dir/verification-result.json" "$source_commit" "$artifact_name" "$actual_sha" "$port" "$health_body" "$inventory_entries" "$managed_json" <<'NODE'
const fs = require('node:fs');
const [resultPath, sourceCommit, artifactName, sha256, port, healthBody, inventoryEntries, managedJson] = process.argv.slice(2);
const managed = JSON.parse(managedJson);
const result = {
  schemaVersion: 1,
  sourceCommit: sourceCommit.toLowerCase(),
  artifactName,
  sha256,
  platform: 'linux-arm64',
  command: 'bin/media-bridge-runtime',
  python: false,
  pythonDirectCall: false,
  inventoryEntries: Number(inventoryEntries),
  forbiddenEntries: 0,
  healthStatus: 200,
  healthBody,
  managedInstall: managed.managedInstall,
  managedPython: managed.managedPython,
  managedCommand: managed.installedCommand,
  managedCommandSha256: managed.installedCommandSha256,
  checksumMismatchRejected: managed.checksumMismatchRejected,
  managedRollbackPreserved: managed.rollbackPreserved,
  verifiedAtUtc: new Date().toISOString(),
};
fs.writeFileSync(resultPath, `${JSON.stringify(result, null, 2)}\n`);
process.stdout.write(JSON.stringify(result));
NODE
