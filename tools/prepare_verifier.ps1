# Install the one Docker verifier image pinned by orchestrate.py.
# The Docker registry manifest is the canonical owner of its blob digests and sizes.
param(
    [ValidateSet('dry-run', 'install', 'verify')]
    [string]$Action = 'dry-run',

    [string]$EvidenceRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Stop-Setup([string]$Problem, [string]$NextStep) {
    throw "$Problem Next: $NextStep"
}

function Get-ImagePin {
    $sourcePath = Join-Path (Split-Path -Parent $PSScriptRoot) 'orchestrate.py'
    if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
        Stop-Setup 'The canonical orchestrate.py image pin is missing.' 'Run this command from the complete jev-harness checkout.'
    }
    $source = Get-Content -LiteralPath $sourcePath -Raw -Encoding UTF8
    $matches = [regex]::Matches($source, '(?m)^VERIFIER_IMAGE = "(docker\.io/library/python@sha256:[0-9a-f]{64})"\s*$')
    if ($matches.Count -ne 1) {
        Stop-Setup 'The canonical VERIFIER_IMAGE pin is missing or ambiguous.' 'Review orchestrate.py and keep exactly one supported immutable image digest.'
    }
    return [ordered]@{ image = $matches[0].Groups[1].Value; source = $sourcePath }
}

function Get-EvidencePath([string]$digest) {
    if ([string]::IsNullOrWhiteSpace($EvidenceRoot)) {
        if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
            Stop-Setup 'LOCALAPPDATA is missing.' 'Pass -EvidenceRoot with a new absolute local directory.'
        }
        $candidate = Join-Path $env:LOCALAPPDATA "JevHarness\verifier-image-$($digest.Substring(0, 12))"
    } else {
        $candidate = $EvidenceRoot
    }
    if ($candidate -notmatch '^[A-Za-z]:[\\/]') {
        Stop-Setup 'EvidenceRoot must be an absolute local drive path.' 'Pass -EvidenceRoot with a new drive-rooted directory.'
    }
    $resolved = [System.IO.Path]::GetFullPath($candidate)
    if ($resolved -match '^[A-Za-z]:[\\/]$' -or
        $resolved -match '(?i)(^|[\\/])jev-harness-runtime([\\/]|$)') {
        Stop-Setup 'EvidenceRoot points to a drive root or the active harness runtime.' 'Choose a separate new subdirectory.'
    }
    return $resolved.TrimEnd([char]'\', [char]'/')
}

function Get-DockerCommand {
    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if ($null -eq $docker) {
        Stop-Setup 'The Docker CLI is missing.' 'Install Docker Desktop with Linux containers and retry.'
    }
    $engine = (& $docker.Source info --format '{{.OSType}}|{{.Architecture}}' 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) {
        Stop-Setup 'The Docker engine is unavailable.' 'Start Docker Desktop in Linux-container mode and retry.'
    }
    if ($engine -cnotmatch '^linux\|(?:x86_64|amd64)$') {
        Stop-Setup "The Docker engine platform is $engine; Linux/amd64 is required." 'Select a Linux/amd64 Docker engine and retry.'
    }
    return $docker.Source
}

function Get-RegistryManifest([string]$dockerPath, [string]$image, [string]$digest) {
    $response = (& $dockerPath manifest inspect --verbose $image 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) {
        Stop-Setup 'The pinned registry manifest could not be read.' 'Check registry access and retry without changing the image pin.'
    }
    try {
        $manifest = $response | ConvertFrom-Json -ErrorAction Stop
        $raw = [Convert]::FromBase64String([string]$manifest.Raw)
    } catch {
        Stop-Setup 'The registry returned an invalid pinned manifest.' 'Inspect Docker registry access and retry.'
    }
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $actualDigest = ([System.BitConverter]::ToString($sha.ComputeHash($raw))).Replace('-', '').ToLowerInvariant()
    } finally {
        $sha.Dispose()
    }
    if ($actualDigest -cne $digest -or
        [string]$manifest.Descriptor.digest -cne "sha256:$digest" -or
        [long]$manifest.Descriptor.size -ne $raw.Length -or
        [string]$manifest.Descriptor.mediaType -cne 'application/vnd.oci.image.manifest.v1+json' -or
        [string]$manifest.Descriptor.platform.os -cne 'linux' -or
        [string]$manifest.Descriptor.platform.architecture -cne 'amd64') {
        Stop-Setup 'The registry manifest identity or Linux/amd64 platform differs from the code pin.' 'Do not pull; inspect the pinned registry artifact.'
    }
    $config = $manifest.OCIManifest.config
    if ([string]$config.digest -cnotmatch '^sha256:[0-9a-f]{64}$' -or
        [long]$config.size -le 0) {
        Stop-Setup 'The pinned registry manifest has invalid config metadata.' 'Inspect the registry artifact before pulling.'
    }
    $layers = @($manifest.OCIManifest.layers)
    if ($layers.Count -lt 1 -or $layers.Count -gt 32) {
        Stop-Setup 'The pinned registry manifest has an unexpected layer count.' 'Inspect the registry artifact before pulling.'
    }
    $seen = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
    $payload = [long]($raw.Length + [long]$config.size)
    $layerPlan = @()
    foreach ($layer in $layers) {
        if ([string]$layer.digest -cnotmatch '^sha256:[0-9a-f]{64}$' -or
            [long]$layer.size -le 0 -or [long]$layer.size -gt 1000000000 -or
            -not $seen.Add([string]$layer.digest)) {
            Stop-Setup 'The pinned registry manifest has invalid or duplicate layer metadata.' 'Inspect the registry artifact before pulling.'
        }
        $payload += [long]$layer.size
        $layerPlan += [ordered]@{digest=[string]$layer.digest; bytes=[long]$layer.size}
    }
    return [ordered]@{
        manifest_bytes = [long]$raw.Length
        config_digest = [string]$config.digest
        config_bytes = [long]$config.size
        layers = $layerPlan
        total_registry_artifact_bytes_if_empty_cache = $payload
    }
}

function Get-LocalImage([string]$dockerPath, [string]$image, [string]$digest, [string]$configDigest) {
    $response = (& $dockerPath image inspect $image --format '{{json .}}' 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) {
        if ($response -match '(?i)no such image') { return $null }
        Stop-Setup 'The local Docker image could not be inspected.' 'Check Docker Desktop and retry.'
    }
    try {
        $local = $response | ConvertFrom-Json -ErrorAction Stop
    } catch {
        Stop-Setup 'Docker returned invalid local image metadata.' 'Inspect the local Docker engine.'
    }
    $expectedSuffix = "@sha256:$digest"
    $matchingDigests = @($local.RepoDigests | Where-Object { [string]$_ -ceq "python$expectedSuffix" -or [string]$_ -ceq "docker.io/library/python$expectedSuffix" })
    if ($matchingDigests.Count -lt 1 -or [string]$local.Os -cne 'linux' -or
        [string]$local.Architecture -cne 'amd64' -or
        ([string]$local.Id -cne "sha256:$digest" -and [string]$local.Id -cne $configDigest)) {
        Stop-Setup 'The local image reference does not match the pinned Linux/amd64 manifest or config identity.' 'Inspect Docker image metadata; do not run the verifier.'
    }
    return [ordered]@{
        id = [string]$local.Id
        os = [string]$local.Os
        architecture = [string]$local.Architecture
        repo_digest = [string]$matchingDigests[0]
    }
}

try {
    if ($env:OS -ne 'Windows_NT') {
        Stop-Setup 'This bootstrap command supports Windows only.' 'Use a Linux-specific Docker setup command on Linux.'
    }
    $pin = Get-ImagePin
    $digest = $pin.image.Split('@')[1].Substring(7)
    $evidencePath = Get-EvidencePath $digest
    $stdoutPath = Join-Path $evidencePath 'pull.stdout.log'
    $stderrPath = Join-Path $evidencePath 'pull.stderr.log'
    $receiptPath = Join-Path $evidencePath 'install.json'
    $dockerPath = Get-DockerCommand
    $registry = Get-RegistryManifest $dockerPath $pin.image $digest
    $local = Get-LocalImage $dockerPath $pin.image $digest $registry.config_digest
    $plan = [ordered]@{
        action = $Action
        image = $pin.image
        pin_source = $pin.source
        platform = 'linux/amd64'
        local_image_present = ($null -ne $local)
        evidence_root = $evidencePath
        evidence_root_exists = [bool](Test-Path -LiteralPath $evidencePath)
        dry_run_writes_bytes = 0
        pull_command = "docker pull --platform linux/amd64 $($pin.image)"
        install_writes = @($evidencePath, $stdoutPath, $stderrPath, $receiptPath,
                           'Docker-managed image store: pinned image manifest, config, listed layers, and engine metadata')
        registry = $registry
    }
    if ($Action -eq 'dry-run') {
        $plan | ConvertTo-Json -Depth 8
        exit 0
    }
    if ($Action -eq 'verify') {
        if ($null -eq $local) {
            Stop-Setup 'The pinned Linux/amd64 verifier image is not installed.' 'Run -Action dry-run, then a watched -Action install.'
        }
        [ordered]@{status='verified'; image=$pin.image; platform='linux/amd64'; local=$local} | ConvertTo-Json -Depth 5
        exit 0
    }
    $plan | ConvertTo-Json -Depth 8
    if ($null -ne $local) {
        Stop-Setup 'The pinned verifier image is already installed; install will not pull or overwrite it.' 'Run -Action verify instead.'
    }
    if (Test-Path -LiteralPath $evidencePath) {
        Stop-Setup 'The verifier evidence root already exists; install never overwrites it.' 'Choose a new empty -EvidenceRoot and rerun the watched install.'
    }
    $parent = Split-Path -Parent $evidencePath
    if (-not (Test-Path -LiteralPath $parent)) {
        $null = New-Item -ItemType Directory -Path $parent -Force -ErrorAction Stop
    }
    $null = New-Item -ItemType Directory -Path $evidencePath -ErrorAction Stop
    Write-Host "Pulling one pinned Docker image. Raw stdout: $stdoutPath ; raw stderr: $stderrPath"
    $pull = Start-Process -FilePath $dockerPath -ArgumentList @('pull', '--platform', 'linux/amd64', $pin.image) `
        -WindowStyle Hidden -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath `
        -PassThru -Wait -ErrorAction Stop
    if ($pull.ExitCode -ne 0) {
        Stop-Setup "Docker pull failed with exit code $($pull.ExitCode); unedited output is in $stdoutPath and $stderrPath." 'Inspect those files and retry into a new evidence root.'
    }
    $installed = Get-LocalImage $dockerPath $pin.image $digest $registry.config_digest
    if ($null -eq $installed) {
        Stop-Setup 'Docker pull exited zero but the pinned image is absent.' 'Inspect the unedited pull output and Docker image store.'
    }
    $receipt = [ordered]@{
        schema = 1
        status = 'installed'
        image = $pin.image
        platform = 'linux/amd64'
        local = $installed
        registry = $registry
        pull_command = $plan.pull_command
        pull_stdout = $stdoutPath
        pull_stderr = $stderrPath
        pull_exit_code = $pull.ExitCode
    }
    $receipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $receiptPath -Encoding UTF8 -NoNewline
    [ordered]@{status='installed'; image=$pin.image; platform='linux/amd64'; evidence=$evidencePath; local=$installed} | ConvertTo-Json -Depth 5
    exit 0
} catch {
    Write-Error "prepare_verifier failed: $($_.Exception.Message)" -ErrorAction Continue
    exit 1
}
