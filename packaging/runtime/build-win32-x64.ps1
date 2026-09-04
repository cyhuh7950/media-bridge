param(
    [Parameter(Mandatory = $true)]
    [string]$Python,
    [Parameter(Mandatory = $true)]
    [string]$Version,
    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory,
    [Parameter(Mandatory = $true)]
    [string]$WorkDirectory,
    [Parameter(Mandatory = $true)]
    [string]$BaseUrl
)

$ErrorActionPreference = 'Stop'

if ($Version -notmatch '^\d+\.\d+\.\d+$') {
    throw 'Version must use x.y.z format.'
}
if (-not [System.IO.Path]::IsPathFullyQualified($OutputDirectory)) {
    throw 'OutputDirectory must be an absolute path.'
}
if (-not [System.IO.Path]::IsPathFullyQualified($WorkDirectory)) {
    throw 'WorkDirectory must be an absolute path.'
}
$artifactBaseUri = [System.Uri]$BaseUrl
$loopbackHosts = @('localhost', '127.0.0.1', '::1')
if ($artifactBaseUri.Scheme -ne 'https' -and -not (
    $artifactBaseUri.Scheme -eq 'http' -and $loopbackHosts -contains $artifactBaseUri.Host
)) {
    throw 'BaseUrl must use HTTPS or loopback HTTP.'
}

$pythonPath = [System.IO.Path]::GetFullPath($Python)
if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw "Python executable is unavailable: $pythonPath"
}
& $pythonPath -c "import platform, struct; assert platform.system() == 'Windows' and struct.calcsize('P') == 8"
if ($LASTEXITCODE -ne 0) {
    throw 'win32-x64 runtime requires 64-bit Windows Python.'
}
& $pythonPath -c "import pathlib, sys; raise SystemExit(86 if (pathlib.Path(sys.base_prefix) / 'conda-meta').is_dir() else 0)"
$pythonDistributionExitCode = $LASTEXITCODE
if ($pythonDistributionExitCode -eq 86) {
    throw 'win32-x64 runtime builds require official CPython; Conda distributions are unsupported.'
}
if ($pythonDistributionExitCode -ne 0) {
    throw 'Unable to verify the Python distribution for the win32-x64 runtime build.'
}

$outputPath = [System.IO.Path]::GetFullPath($OutputDirectory)
$workPath = [System.IO.Path]::GetFullPath($WorkDirectory)
$pyInstallerDist = Join-Path $workPath 'pyinstaller-dist'
$pyInstallerWork = Join-Path $workPath 'pyinstaller-work'
$pyInstallerSpec = Join-Path $workPath 'pyinstaller-spec'
$payloadPath = Join-Path $workPath 'payload'
$entrypointPath = Join-Path $PSScriptRoot 'entrypoint.py'
$sourceRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))

foreach ($target in @($pyInstallerDist, $pyInstallerWork, $pyInstallerSpec, $payloadPath)) {
    if (Test-Path -LiteralPath $target) {
        Remove-Item -LiteralPath $target -Recurse -Force
    }
}
New-Item -ItemType Directory -Force -Path $outputPath, $workPath | Out-Null

Push-Location -LiteralPath $workPath
try {
    & $pythonPath -m PyInstaller `
        --noconfirm `
        --clean `
        --onedir `
        --name media-bridge-runtime `
        --paths $sourceRoot `
        --distpath $pyInstallerDist `
        --workpath $pyInstallerWork `
        --specpath $pyInstallerSpec `
        $entrypointPath
    $pyInstallerExitCode = $LASTEXITCODE
} finally {
    Pop-Location
}
if ($pyInstallerExitCode -ne 0) {
    throw 'PyInstaller runtime build failed.'
}

$builtRoot = Join-Path $pyInstallerDist 'media-bridge-runtime'
$builtExecutable = Join-Path $builtRoot 'media-bridge-runtime.exe'
if (-not (Test-Path -LiteralPath $builtExecutable -PathType Leaf)) {
    throw 'PyInstaller output executable is missing.'
}

$payloadBin = Join-Path $payloadPath 'bin'
New-Item -ItemType Directory -Force -Path $payloadBin | Out-Null
Copy-Item -Path (Join-Path $builtRoot '*') -Destination $payloadBin -Recurse -Force

$artifactName = "media-bridge-runtime-$Version-win32-x64.tar.gz"
$artifactPath = Join-Path $outputPath $artifactName
$checksumPath = "$artifactPath.sha256"
$manifestPath = Join-Path $outputPath 'runtime-manifest.json'
foreach ($target in @($artifactPath, $checksumPath, $manifestPath)) {
    if (Test-Path -LiteralPath $target) {
        Remove-Item -LiteralPath $target -Force
    }
}

$windowsRoot = $env:SystemRoot
if ([string]::IsNullOrWhiteSpace($windowsRoot)) {
    throw 'Windows system root is unavailable.'
}
$tarPath = Join-Path $windowsRoot 'System32\tar.exe'
if (-not (Test-Path -LiteralPath $tarPath -PathType Leaf)) {
    throw "Windows system tar is unavailable: $tarPath"
}
& $tarPath -czf $artifactPath -C $payloadPath .
if ($LASTEXITCODE -ne 0) {
    throw 'runtime archive creation failed.'
}
$sha256 = (Get-FileHash -LiteralPath $artifactPath -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -LiteralPath $checksumPath -Value "$sha256  $artifactName" -Encoding utf8NoBOM

$artifactUrl = "$($BaseUrl.TrimEnd('/'))/$artifactName"
$manifest = [ordered]@{
    schemaVersion = 1
    packageVersion = $Version
    artifacts = [ordered]@{
        'win32-x64' = [ordered]@{
            version = $Version
            published = $true
            url = $artifactUrl
            sha256 = $sha256
            archive = 'tar.gz'
            command = 'bin/media-bridge-runtime.exe'
            python = $false
        }
    }
}
$manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $manifestPath -Encoding utf8NoBOM

[ordered]@{
    artifact = $artifactPath
    checksum = $checksumPath
    manifest = $manifestPath
    sha256 = $sha256
    bytes = (Get-Item -LiteralPath $artifactPath).Length
} | ConvertTo-Json -Compress
