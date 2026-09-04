param(
    [Parameter(Mandatory = $true)]
    [string]$ArtifactDirectory,
    [Parameter(Mandatory = $true)]
    [string]$TestRoot,
    [Parameter(Mandatory = $true)]
    [string]$SourceCommit,
    [int]$Port = 0
)

$ErrorActionPreference = 'Stop'

function Assert-AbsolutePath {
    param([string]$Value, [string]$Name)
    if (-not [System.IO.Path]::IsPathFullyQualified($Value)) {
        throw "$Name must be an absolute path."
    }
}

Assert-AbsolutePath -Value $ArtifactDirectory -Name 'ArtifactDirectory'
Assert-AbsolutePath -Value $TestRoot -Name 'TestRoot'
if ($SourceCommit -notmatch '^[0-9a-fA-F]{7,64}$') {
    throw 'SourceCommit must be a hexadecimal Git commit identifier.'
}
if ($Port -lt 0 -or $Port -gt 65535) {
    throw 'Port must be 0 or a valid TCP port.'
}
if (-not [Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -notmatch 'AMD64') {
    throw 'win32-x64 verification requires 64-bit Windows.'
}

$artifactRoot = [System.IO.Path]::GetFullPath($ArtifactDirectory)
$testPath = [System.IO.Path]::GetFullPath($TestRoot)
if (-not (Test-Path -LiteralPath $artifactRoot -PathType Container)) {
    throw "ArtifactDirectory does not exist: $artifactRoot"
}
if (Test-Path -LiteralPath $testPath) {
    throw "TestRoot must not already exist: $testPath"
}

$artifacts = @(Get-ChildItem -LiteralPath $artifactRoot -File -Filter 'media-bridge-runtime-*-win32-x64.tar.gz')
if ($artifacts.Count -ne 1) {
    throw 'ArtifactDirectory must contain exactly one win32-x64 runtime archive.'
}
$artifact = $artifacts[0]
$checksumPath = "$($artifact.FullName).sha256"
$manifestPath = Join-Path $artifactRoot 'runtime-manifest.json'
if (-not (Test-Path -LiteralPath $checksumPath -PathType Leaf)) {
    throw "Checksum file is missing: $checksumPath"
}
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw "Runtime manifest is missing: $manifestPath"
}

$checksumLine = (Get-Content -Raw -LiteralPath $checksumPath).Trim()
if ($checksumLine -notmatch '^(?<sha>[0-9a-fA-F]{64})\s{2}(?<name>.+)$') {
    throw 'Checksum file must contain SHA-256, two spaces, and the artifact filename.'
}
$expectedSha = $Matches.sha.ToLowerInvariant()
if ($Matches.name -ne $artifact.Name) {
    throw 'Checksum filename does not match the runtime archive.'
}
$actualSha = (Get-FileHash -LiteralPath $artifact.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualSha -ne $expectedSha) {
    throw 'Runtime archive SHA-256 does not match its checksum file.'
}

$manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
$entry = $manifest.artifacts.'win32-x64'
if ($manifest.schemaVersion -ne 1 -or $null -eq $entry) {
    throw 'Runtime manifest does not contain schema 1 win32-x64 metadata.'
}
if (-not $entry.published -or $entry.sha256 -ne $actualSha) {
    throw 'Runtime manifest publication state or SHA-256 does not match the archive.'
}
if ($entry.archive -ne 'tar.gz' -or $entry.command -ne 'bin/media-bridge-runtime.exe' -or $entry.python -ne $false) {
    throw 'Runtime manifest command contract is invalid.'
}

$windowsRoot = $env:SystemRoot
if ([string]::IsNullOrWhiteSpace($windowsRoot)) {
    throw 'Windows system root is unavailable.'
}
$tarPath = Join-Path $windowsRoot 'System32\tar.exe'
if (-not (Test-Path -LiteralPath $tarPath -PathType Leaf)) {
    throw "Windows system tar is unavailable: $tarPath"
}

$process = $null
$healthStatus = $null
$healthBody = $null
$selectedPort = $Port
try {
    New-Item -ItemType Directory -Path $testPath | Out-Null
    $extractPath = Join-Path $testPath 'extracted'
    $assetPath = Join-Path $testPath 'assets'
    New-Item -ItemType Directory -Path $extractPath, $assetPath | Out-Null

    $inventory = @(& $tarPath -tzf $artifact.FullName)
    if ($LASTEXITCODE -ne 0) {
        throw 'Runtime archive inventory failed.'
    }
    $normalizedInventory = @($inventory | ForEach-Object { ($_ -replace '\\', '/').TrimStart('.', '/') })
    $forbidden = @($normalizedInventory | Where-Object {
        $_ -match '(?i)(^|/)(tests?|credentials?|secrets?)(/|$)' -or
        $_ -match '(?i)(^|/)\.env($|\.)' -or
        $_ -match '(?i)(^|/)config\.json$' -or
        $_ -match '(?i)\.py$'
    })
    if ($forbidden.Count -ne 0) {
        throw "Runtime archive contains forbidden entries: $($forbidden -join ', ')"
    }
    if ($normalizedInventory -notcontains $entry.command) {
        throw 'Runtime archive does not contain the manifest command.'
    }

    & $tarPath -xzf $artifact.FullName -C $extractPath
    if ($LASTEXITCODE -ne 0) {
        throw 'Runtime archive extraction failed.'
    }
    $runtimeCommand = Join-Path $extractPath ($entry.command -replace '/', '\')
    if (-not (Test-Path -LiteralPath $runtimeCommand -PathType Leaf)) {
        throw 'Extracted runtime command is missing.'
    }

    if ($selectedPort -eq 0) {
        $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
        $listener.Start()
        try {
            $selectedPort = ([System.Net.IPEndPoint]$listener.LocalEndpoint).Port
        } finally {
            $listener.Stop()
        }
    }

    $registryPath = Join-Path $testPath 'model-registry.yaml'
    $configPath = Join-Path $testPath 'config.json'
    @"
version: "external-retest"
models:
  - id: solar-pro4
    input_modalities: [text]
    expires_at: 2099-01-01T00:00:00Z
    pdf_passthrough_verified: false
"@ | Set-Content -LiteralPath $registryPath -Encoding utf8NoBOM
    [ordered]@{
        runtimeMode = 'personal'
        host = '127.0.0.1'
        port = $selectedPort
        opencodex = [ordered]@{ baseUrl = "http://127.0.0.1:$selectedPort/v1" }
        solar = [ordered]@{
            model = 'solar-pro4'
            endpoint = 'https://127.0.0.1:9/v1/chat/completions'
            apiKeyEnv = 'SOLAR_API_KEY'
        }
        ocr = [ordered]@{
            model = 'document-parse'
            endpoint = 'https://127.0.0.1:9/v1/document-digitization'
            apiKeyEnv = 'SOLAR_API_KEY'
        }
        conversion = [ordered]@{ maxBytes = 8388608; ocrEnabled = $true; visionEnabled = $true }
        failurePolicy = [ordered]@{ blockSolarOnPreparationFailure = $true }
    } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $configPath -Encoding utf8NoBOM

    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $runtimeCommand
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.Environment['MEDIA_BRIDGE_CONFIG_FILE'] = $configPath
    $startInfo.Environment['MEDIA_BRIDGE_MODEL_REGISTRY'] = $registryPath
    $startInfo.Environment['MEDIA_BRIDGE_ASSET_ROOT'] = $assetPath
    $startInfo.Environment['MEDIA_BRIDGE_RECEIPT_SECRET'] = 'external-retest-receipt-secret-0001'
    $startInfo.Environment['MEDIA_BRIDGE_SERVICE_TOKEN'] = 'external-retest-service-token-0001'
    $startInfo.Environment['MEDIA_BRIDGE_RUNTIME_MODE'] = 'personal'
    $startInfo.Environment['MEDIA_BRIDGE_SOLAR_MODEL'] = 'solar-pro4'
    $startInfo.Environment['MEDIA_BRIDGE_SOLAR_ENDPOINT'] = 'https://127.0.0.1:9/v1/chat/completions'
    $startInfo.Environment['MEDIA_BRIDGE_SOLAR_CREDENTIAL_ENV'] = 'SOLAR_API_KEY'
    $startInfo.Environment['MEDIA_BRIDGE_OCR_ENDPOINT'] = 'https://127.0.0.1:9/v1/document-digitization'
    $startInfo.Environment['MEDIA_BRIDGE_OCR_CREDENTIAL_ENV'] = 'SOLAR_API_KEY'
    $startInfo.Environment['SOLAR_API_KEY'] = 'external-retest-provider-key-0001'
    $startInfo.Environment['MEDIA_BRIDGE_MAX_REQUEST_BYTES'] = '8388608'
    $startInfo.Environment['MEDIA_BRIDGE_HTTP_HOST'] = '127.0.0.1'
    $startInfo.Environment['MEDIA_BRIDGE_HTTP_PORT'] = [string]$selectedPort

    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    if (-not $process.Start()) {
        throw 'Runtime process did not start.'
    }

    $healthUri = "http://127.0.0.1:$selectedPort/health"
    $deadline = [DateTime]::UtcNow.AddSeconds(30)
    while ([DateTime]::UtcNow -lt $deadline) {
        if ($process.HasExited) {
            $stdout = $process.StandardOutput.ReadToEnd()
            $stderr = $process.StandardError.ReadToEnd()
            throw "Runtime exited before health succeeded. stdout=$stdout stderr=$stderr"
        }
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $healthUri -TimeoutSec 2
            if ($response.StatusCode -eq 200) {
                $healthStatus = $response.StatusCode
                $healthBody = $response.Content
                break
            }
        } catch {
            Start-Sleep -Milliseconds 250
        }
    }
    if ($healthStatus -ne 200) {
        throw 'Runtime /health did not return HTTP 200 within 30 seconds.'
    }

    $managedVerifier = Join-Path $PSScriptRoot 'verify-managed-runtime.cjs'
    if (-not (Test-Path -LiteralPath $managedVerifier -PathType Leaf)) {
        throw 'Managed runtime verifier is missing.'
    }
    $managedOutput = & node $managedVerifier $artifactRoot (Join-Path $testPath 'managed-runtime')
    if ($LASTEXITCODE -ne 0) {
        throw 'Managed runtime install and rollback verification failed.'
    }
    $managedResult = $managedOutput | ConvertFrom-Json
    if (-not $managedResult.managedInstall -or $managedResult.managedPython -ne $false -or
        -not $managedResult.checksumMismatchRejected -or -not $managedResult.rollbackPreserved) {
        throw 'Managed runtime verification result is incomplete.'
    }

    $result = [ordered]@{
        schemaVersion = 1
        sourceCommit = $SourceCommit.ToLowerInvariant()
        artifactName = $artifact.Name
        bytes = $artifact.Length
        sha256 = $actualSha
        packageVersion = $manifest.packageVersion
        runtimeVersion = $entry.version
        platform = 'win32-x64'
        command = $entry.command
        python = $false
        launchedExecutable = $runtimeCommand
        pythonDirectCall = $false
        inventoryEntries = $normalizedInventory.Count
        forbiddenEntries = $forbidden.Count
        healthStatus = $healthStatus
        healthBody = $healthBody
        managedInstall = $managedResult.managedInstall
        managedPython = $managedResult.managedPython
        managedCommand = $managedResult.installedCommand
        managedCommandSha256 = $managedResult.installedCommandSha256
        checksumMismatchRejected = $managedResult.checksumMismatchRejected
        managedRollbackPreserved = $managedResult.rollbackPreserved
        verifiedAtUtc = [DateTime]::UtcNow.ToString('o')
    }
    $resultPath = Join-Path $artifactRoot 'verification-result.json'
    $resultJson = $result | ConvertTo-Json -Depth 5
    Set-Content -LiteralPath $resultPath -Value $resultJson -Encoding utf8NoBOM
    $result | ConvertTo-Json -Depth 5 -Compress
} finally {
    if ($null -ne $process) {
        if (-not $process.HasExited) {
            $process.Kill($true)
            $process.WaitForExit(10000) | Out-Null
        }
        $process.Dispose()
    }
    if (Test-Path -LiteralPath $testPath) {
        Remove-Item -LiteralPath $testPath -Recurse -Force
    }
}
