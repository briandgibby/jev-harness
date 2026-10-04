# Reproduce one pinned, local OpenVINO Model Server coding model on Windows.
# Sources: https://github.com/openvinotoolkit/model_server/releases/tag/v2026.4.0
# https://docs.openvino.ai/2026/model-server/ovms_demos_code_completion_vsc.html
# https://docs.openvino.ai/2026/model-server/ovms_docs_parameters.html
param(
    [ValidateSet('dry-run', 'install', 'serve', 'verify')]
    [string]$Action = 'dry-run',

    [ValidateSet('fast', 'strong')]
    [string]$Model = 'fast',

    [string]$Root,

    [ValidateRange(1024, 65535)]
    [int]$Port = 8000,

    [ValidateRange(1024, 65535)]
    [int]$GrpcPort = 9001,

    [ValidateRange(10, 900)]
    [int]$ReadyTimeoutSeconds = 300
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$package = [ordered]@{
    version = 'v2026.4.0'
    url = 'https://github.com/openvinotoolkit/model_server/releases/download/v2026.4.0/ovms_windows_2026.4.0_python_off.zip'
    bytes = [long]117195695
    sha256 = '46d03114c97abfe05f2c5a8fde772c655aeef541ee254c23f402f81a616474e3'
    extracted_bytes = [long]323472932
    entries = 526
    exe_sha256 = '1e95e9b523310fcf29b520ded3d750504e4db8d2fe472669155ff5975b6add83'
    setupvars_sha256 = 'd28fc742ea9f3cf18d05437d7dfa078284970e9595bbdb8c465e25d05b2a36a1'
    hf_version = '1.24.0'
}

function Stop-Setup([string]$Problem, [string]$NextStep) {
    throw "$Problem Next: $NextStep"
}

function Assert-ExactKeys([object]$value, [string[]]$required, [string]$label) {
    if ($value -isnot [System.Collections.IDictionary]) {
        Stop-Setup "$label must be a JSON object." 'Correct model-pins.json before retrying.'
    }
    $actual = @($value.Keys)
    if ($actual.Count -ne $required.Count) {
        Stop-Setup "$label has missing or unexpected keys." 'Correct model-pins.json before retrying.'
    }
    foreach ($key in $actual) {
        if ($required -cnotcontains [string]$key) {
            Stop-Setup "$label has an unexpected key: $key." 'Correct model-pins.json before retrying.'
        }
    }
}

function Get-ModelPins {
    $pinPath = Join-Path (Split-Path -Parent $PSScriptRoot) 'model-pins.json'
    if (-not (Test-Path -LiteralPath $pinPath -PathType Leaf)) {
        Stop-Setup 'The canonical model-pins.json file is missing.' 'Restore the complete jev-harness checkout before retrying.'
    }
    try {
        $data = Get-Content -LiteralPath $pinPath -Raw -Encoding UTF8 | ConvertFrom-Json -AsHashtable -ErrorAction Stop
    } catch {
        Stop-Setup 'The canonical model-pins.json file is invalid JSON.' 'Correct that file before retrying.'
    }
    Assert-ExactKeys $data @('schema_version', 'models') 'model-pins.json'
    if ($data.schema_version -isnot [long] -or $data.schema_version -ne 1) {
        Stop-Setup 'model-pins.json schema_version must be the integer 1.' 'Use the supported schema before retrying.'
    }
    Assert-ExactKeys $data.models @('fast', 'strong') 'model-pins.json models'
    $validated = @{}
    foreach ($route in @('fast', 'strong')) {
        $row = $data.models[$route]
        Assert-ExactKeys $row @('id', 'provider_model', 'hf_repo', 'hf_revision', 'bytes',
                                 'file_count', 'weights_sha256', 'tool_parser') "model-pins.json $route"
        if ($row.id -isnot [string] -or $row.id -cnotmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$') {
            Stop-Setup "model-pins.json $route.id is invalid." 'Use a 1–64 character safe model ID.'
        }
        if ($row.provider_model -isnot [string] -or
            $row.provider_model -cnotmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$') {
            Stop-Setup "model-pins.json $route.provider_model is invalid." 'Use a 1–64 character safe provider model name.'
        }
        if ($row.hf_repo -isnot [string] -or
            $row.hf_repo -cnotmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}/[A-Za-z0-9][A-Za-z0-9._-]{0,127}$') {
            Stop-Setup "model-pins.json $route.hf_repo is invalid." 'Use an owner/repository Hugging Face name.'
        }
        if ($row.hf_revision -isnot [string] -or $row.hf_revision -cnotmatch '^[0-9a-f]{40}$') {
            Stop-Setup "model-pins.json $route.hf_revision is invalid." 'Pin a lowercase 40-character commit SHA.'
        }
        if ($row.bytes -isnot [long] -or $row.bytes -lt 1 -or $row.bytes -gt 50000000000) {
            Stop-Setup "model-pins.json $route.bytes is outside the supported range." 'Use an integer from 1 to 50000000000.'
        }
        if ($row.file_count -isnot [long] -or $row.file_count -lt 1 -or $row.file_count -gt 256) {
            Stop-Setup "model-pins.json $route.file_count is outside the supported range." 'Use an integer from 1 to 256.'
        }
        if ($row.weights_sha256 -isnot [string] -or $row.weights_sha256 -cnotmatch '^[0-9a-f]{64}$') {
            Stop-Setup "model-pins.json $route.weights_sha256 is invalid." 'Pin a lowercase 64-character SHA-256 digest.'
        }
        if ($null -ne $row.tool_parser -and
            ($row.tool_parser -isnot [string] -or $row.tool_parser -cne 'qwen3coder')) {
            Stop-Setup "model-pins.json $route.tool_parser is unsupported." 'Use null or qwen3coder.'
        }
        $validated[$route] = [ordered]@{
            id = $row.id
            repository = $row.hf_repo
            revision = $row.hf_revision
            bytes = [long]$row.bytes
            file_count = [int]$row.file_count
            served_name = $row.provider_model
            weights_sha256 = $row.weights_sha256
            tool_parser = $row.tool_parser
        }
    }
    if ($validated.fast.id -ceq $validated.strong.id -or
        $validated.fast.served_name -ceq $validated.strong.served_name) {
        Stop-Setup 'The fast and strong model names must be distinct.' 'Correct model-pins.json before retrying.'
    }
    return [ordered]@{source=$pinPath; models=$validated}
}

function Get-RootPath {
    if ([string]::IsNullOrWhiteSpace($Root)) {
        if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
            Stop-Setup 'LOCALAPPDATA is missing.' 'Pass -Root with a new absolute local directory.'
        }
        $candidate = Join-Path $env:LOCALAPPDATA "JevHarness\ovms-$($package.version)-$Model"
    } else {
        $candidate = $Root
    }
    if ($candidate -notmatch '^[A-Za-z]:[\\/]') {
        Stop-Setup 'Root must be an absolute local drive path.' 'Set -Root to a new drive-rooted directory.'
    }
    $resolved = [System.IO.Path]::GetFullPath($candidate)
    if ($resolved -match '^[A-Za-z]:[\\/]$') {
        Stop-Setup 'Root cannot be the drive root.' 'Choose a new subdirectory with -Root.'
    }
    if ($resolved -match '(?i)(^|[\\/])jev-harness-runtime([\\/]|$)') {
        Stop-Setup 'Root points into the active jev-harness-runtime tree.' 'Choose a separate empty directory.'
    }
    return $resolved.TrimEnd([char]'\', [char]'/')
}

function Get-GpuDevice {
    $adapters = @(Get-CimInstance Win32_VideoController -ErrorAction Stop)
    $b70 = @($adapters | Where-Object { $_.Name -like '*Arc*Pro B70*' })
    if ($b70.Count -ne 1) {
        Stop-Setup 'Expected exactly one Intel Arc Pro B70 adapter; the hardware check failed.' 'Check Device Manager and the Intel graphics driver.'
    }
    $otherIntelDiscrete = @($adapters | Where-Object {
        $_.Name -like '*Intel*Arc*' -and $_.Name -notlike '*Arc*Pro B70*'
    })
    if ($otherIntelDiscrete.Count -gt 0) {
        Stop-Setup 'Additional Intel Arc adapters make the OpenVINO GPU index ambiguous.' 'Use a single visible Intel discrete GPU for this bounded setup.'
    }
    $integrated = @($adapters | Where-Object {
        $_.Name -like '*Intel*Graphics*' -and $_.Name -notlike '*Arc*Pro B70*'
    })
    if ($integrated.Count -gt 1) {
        Stop-Setup 'Multiple integrated Intel GPU entries make the OpenVINO GPU index ambiguous.' 'Check adapter enumeration before serving.'
    }
    # OpenVINO enumerates an Intel iGPU first, then Intel discrete GPUs.
    # https://docs.openvino.ai/2026/openvino-workflow/running-inference/inference-devices-and-modes/gpu-device.html
    if ($integrated.Count -eq 1) { return 'GPU.1' }
    return 'GPU.0'
}

function Show-Plan([string]$rootPath, [string]$gpuDevice) {
    $knownDownload = [long]($package.bytes + $selection.bytes)
    $minimumFree = [long](2 * $selection.bytes + $package.bytes + $package.extracted_bytes + 1073741824)
    [ordered]@{
        action = $Action
        model = $Model
        model_pin_source = $pinSource
        model_repository = $selection.repository
        model_revision = $selection.revision
        model_id = $selection.id
        provider_model = $selection.served_name
        root = $rootPath
        root_exists = [bool](Test-Path -LiteralPath $rootPath)
        dry_run_writes_bytes = 0
        download_bytes = $knownDownload
        ovms_zip_bytes = $package.bytes
        ovms_extracted_bytes = $package.extracted_bytes
        model_snapshot_bytes = $selection.bytes
        model_file_count = $selection.file_count
        hf_cli_version = $package.hf_version
        minimum_free_bytes_with_download_headroom = $minimumFree
        install_paths = @(
            $rootPath,
            (Join-Path $rootPath 'ovms.zip'),
            (Join-Path $rootPath 'ovms'),
            (Join-Path $rootPath 'model'),
            (Join-Path $rootPath 'model\.cache\huggingface'),
            (Join-Path $rootPath 'hf-home'),
            (Join-Path $rootPath 'download.stdout.log'),
            (Join-Path $rootPath 'download.stderr.log'),
            (Join-Path $rootPath 'install.json')
        )
        serve_writes = 'new server stdout/stderr logs within root only; model and package stay unchanged'
        bind = "127.0.0.1:$Port"
        grpc_bind = "127.0.0.1:$GrpcPort"
        gpu_device = $gpuDevice
    } | ConvertTo-Json -Depth 5
}

function Assert-EnoughDisk([string]$rootPath) {
    $driveLetter = $rootPath.Substring(0, 1)
    $drive = [System.IO.DriveInfo]::new($driveLetter)
    $minimumFree = [long](2 * $selection.bytes + $package.bytes + $package.extracted_bytes + 1073741824)
    if (-not $drive.IsReady -or $drive.AvailableFreeSpace -lt $minimumFree) {
        Stop-Setup "Insufficient free space on drive $driveLetter; need at least $minimumFree bytes for this model and download headroom." 'Choose a drive with enough space using -Root.'
    }
}

function Get-PinnedModelMetadata {
    $uri = "https://huggingface.co/api/models/$($selection.repository)/revision/$($selection.revision)?blobs=true"
    try {
        $metadata = Invoke-RestMethod -Uri $uri -TimeoutSec 30 -ErrorAction Stop
    } catch {
        Stop-Setup 'The pinned Hugging Face model manifest could not be read.' 'Check network access and retry the same pinned install command.'
    }
    if ($metadata.sha -cne $selection.revision) {
        Stop-Setup 'The model manifest revision differs from the pinned revision.' 'Inspect the repository and do not use a mutable branch.'
    }
    $files = @($metadata.siblings)
    $total = [long]0
    $paths = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
    foreach ($item in $files) {
        if ($item.rfilename -notmatch '^[A-Za-z0-9._/-]+$' -or
            $item.rfilename -match '(^|/)\.\.($|/)' -or
            $item.rfilename.StartsWith('/')) {
            Stop-Setup 'The model manifest contains an unsafe path.' 'Inspect the pinned model repository before installing.'
        }
        if (-not $paths.Add([string]$item.rfilename) -or
            [string]$item.blobId -cnotmatch '^[0-9a-f]{40}$' -or
            [long]$item.size -lt 0 -or [long]$item.size -gt $selection.bytes) {
            Stop-Setup 'The model manifest contains a duplicate path or invalid file metadata.' 'Inspect the pinned model repository before installing.'
        }
        if ($null -ne $item.PSObject.Properties['lfs'] -and $null -ne $item.lfs -and
            [string]$item.lfs.sha256 -cnotmatch '^[0-9a-f]{64}$') {
            Stop-Setup 'The model manifest contains an invalid LFS digest.' 'Inspect the pinned model repository before installing.'
        }
        $total += [long]$item.size
    }
    if ($files.Count -ne $selection.file_count -or $total -ne $selection.bytes) {
        Stop-Setup 'The model manifest size or file count differs from the pinned specification.' 'Review and repin the model as a deliberate change.'
    }
    $weights = @($files | Where-Object { $_.rfilename -ceq 'openvino_model.bin' })
    if ($weights.Count -ne 1 -or $null -eq $weights[0].lfs -or
        [string]$weights[0].lfs.sha256 -cne $selection.weights_sha256) {
        Stop-Setup 'The model weights digest differs from the pinned specification.' 'Review and repin the model as a deliberate change.'
    }
    return $files
}

function Assert-Package([string]$rootPath) {
    $zipPath = Join-Path $rootPath 'ovms.zip'
    if (-not (Test-Path -LiteralPath $zipPath -PathType Leaf)) {
        Stop-Setup 'The pinned OVMS archive is missing.' 'Run -Action install in a new empty root.'
    }
    $zip = Get-Item -LiteralPath $zipPath -ErrorAction Stop
    if ($zip.Length -ne $package.bytes -or
        (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $package.sha256) {
        Stop-Setup 'The OpenVINO Model Server archive failed size or SHA-256 verification.' 'Do not extract or run it; choose a fresh root and retry.'
    }
}

function Assert-ExtractedPackage([string]$rootPath) {
    $zipPath = Join-Path $rootPath 'ovms.zip'
    $archive = [System.IO.Compression.ZipFile]::OpenRead($zipPath)
    $expected = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    try {
        foreach ($entry in $archive.Entries) {
            if ([string]::IsNullOrEmpty($entry.Name)) { continue }
            if (-not $entry.FullName.StartsWith('ovms/') -or
                $entry.FullName -match '(^|/)\.\.($|/)' -or $entry.FullName.Contains('\')) {
                Stop-Setup 'The pinned OVMS archive has an unsafe path.' 'Inspect the package before serving.'
            }
            $relative = $entry.FullName.Replace('/', '\')
            if (-not $expected.Add($relative)) {
                Stop-Setup 'The pinned OVMS archive has a duplicate file path.' 'Inspect the package before serving.'
            }
            $filePath = Join-Path $rootPath $relative
            if (-not (Test-Path -LiteralPath $filePath -PathType Leaf)) {
                Stop-Setup "Extracted OVMS file $relative is missing." 'Choose a fresh root and repeat the pinned install.'
            }
            $file = Get-Item -LiteralPath $filePath
            if (($file.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -or
                $file.Length -ne $entry.Length) {
                Stop-Setup "Extracted OVMS file $relative is a link or has the wrong byte length." 'Choose a fresh root and repeat the pinned install.'
            }
            $entryStream = $entry.Open()
            $sha = [System.Security.Cryptography.SHA256]::Create()
            try {
                $archiveDigest = ([System.BitConverter]::ToString($sha.ComputeHash($entryStream))).Replace('-', '').ToLowerInvariant()
            } finally {
                $sha.Dispose()
                $entryStream.Dispose()
            }
            if ((Get-FileHash -LiteralPath $filePath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $archiveDigest) {
                Stop-Setup "Extracted OVMS file $relative differs from the pinned archive." 'Choose a fresh root and repeat the pinned install.'
            }
        }
    } finally {
        $archive.Dispose()
    }
    $actualFiles = @(Get-ChildItem -LiteralPath (Join-Path $rootPath 'ovms') -Recurse -File -Force)
    foreach ($file in $actualFiles) {
        $relative = [System.IO.Path]::GetRelativePath($rootPath, $file.FullName)
        if (-not $expected.Contains($relative)) {
            Stop-Setup "Unexpected extracted OVMS file $relative was found." 'Inspect the root and reinstall into a new directory.'
        }
    }
    $exePath = Join-Path $rootPath 'ovms\ovms.exe'
    $setupPath = Join-Path $rootPath 'ovms\setupvars.ps1'
    foreach ($pair in @(
        @($exePath, $package.exe_sha256),
        @($setupPath, $package.setupvars_sha256)
    )) {
        if (-not (Test-Path -LiteralPath $pair[0] -PathType Leaf) -or
            (Get-FileHash -LiteralPath $pair[0] -Algorithm SHA256).Hash.ToLowerInvariant() -cne $pair[1]) {
            Stop-Setup 'An extracted OVMS executable or setup script failed SHA-256 verification.' 'Choose a fresh root and repeat the pinned install.'
        }
    }
}

function Get-GitBlobSha1([string]$filePath, [long]$length) {
    $stream = [System.IO.File]::OpenRead($filePath)
    $sha = [System.Security.Cryptography.SHA1]::Create()
    try {
        $prefix = [System.Text.Encoding]::ASCII.GetBytes("blob $length`0")
        $null = $sha.TransformBlock($prefix, 0, $prefix.Length, $prefix, 0)
        $buffer = New-Object byte[] 1048576
        while (($read = $stream.Read($buffer, 0, $buffer.Length)) -gt 0) {
            $null = $sha.TransformBlock($buffer, 0, $read, $buffer, 0)
        }
        $null = $sha.TransformFinalBlock([byte[]]::new(0), 0, 0)
        return ([System.BitConverter]::ToString($sha.Hash)).Replace('-', '').ToLowerInvariant()
    } finally {
        $stream.Dispose()
        $sha.Dispose()
    }
}

function Assert-ModelFiles([string]$rootPath, [object[]]$files) {
    $modelPath = Join-Path $rootPath 'model'
    $expected = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
    $total = [long]0
    foreach ($item in $files) {
        $name = [string]$item.rfilename
        if ($name -notmatch '^[A-Za-z0-9._/-]+$' -or $name -match '(^|/)\.\.($|/)' -or $name.StartsWith('/')) {
            Stop-Setup 'The stored model manifest contains an unsafe path.' 'Inspect install.json and reinstall into a fresh root.'
        }
        if (-not $expected.Add($name)) {
            Stop-Setup 'The model manifest contains a duplicate path.' 'Inspect the pinned model repository.'
        }
        $filePath = Join-Path $modelPath ($name.Replace('/', '\'))
        if (-not (Test-Path -LiteralPath $filePath -PathType Leaf)) {
            Stop-Setup "Model file $name is missing." 'Reinstall into a fresh root.'
        }
        $file = Get-Item -LiteralPath $filePath -ErrorAction Stop
        if ($file.PSIsContainer -or ($file.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) {
            Stop-Setup "Model file $name is missing, a directory, or a link." 'Reinstall into a fresh root.'
        }
        if ($file.Length -ne [long]$item.size) {
            Stop-Setup "Model file $name has the wrong byte length." 'Reinstall into a fresh root.'
        }
        $total += $file.Length
        if ($null -ne $item.PSObject.Properties['lfs'] -and $null -ne $item.lfs) {
            $digest = (Get-FileHash -LiteralPath $filePath -Algorithm SHA256).Hash.ToLowerInvariant()
            $expectedDigest = if ($name -ceq 'openvino_model.bin') { $selection.weights_sha256 } else { [string]$item.lfs.sha256 }
            if ($digest -cne $expectedDigest) {
                Stop-Setup "Model file $name failed SHA-256 verification." 'Reinstall into a fresh root.'
            }
        } elseif ((Get-GitBlobSha1 $filePath $file.Length) -cne [string]$item.blobId) {
            Stop-Setup "Model file $name failed Git blob SHA-1 verification." 'Reinstall into a fresh root.'
        }
    }
    if ($expected.Count -ne $selection.file_count -or $total -ne $selection.bytes) {
        Stop-Setup 'The installed model does not match the pinned byte count.' 'Reinstall into a fresh root.'
    }
    $actualFiles = @(Get-ChildItem -LiteralPath $modelPath -Recurse -File -Force)
    foreach ($file in $actualFiles) {
        $relative = [System.IO.Path]::GetRelativePath($modelPath, $file.FullName).Replace('\', '/')
        if ($relative.StartsWith('.cache/huggingface/')) { continue }
        if (-not $expected.Contains($relative)) {
            Stop-Setup "Unexpected model file $relative was found." 'Inspect the directory before serving; do not reuse this root.'
        }
    }
}

function Get-InstalledManifest([string]$rootPath) {
    $manifestPath = Join-Path $rootPath 'install.json'
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        Stop-Setup 'The install manifest is missing.' 'Run -Action install in a new empty root.'
    }
    try {
        $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json -ErrorAction Stop
    } catch {
        Stop-Setup 'The install manifest is invalid JSON.' 'Inspect the failed install and use a new empty root.'
    }
    if ($manifest.schema -ne 1 -or $manifest.model -cne $Model -or
        $manifest.model_repository -cne $selection.repository -or
        $manifest.model_revision -cne $selection.revision -or
        $manifest.model_id -cne $selection.served_name -or
        $manifest.package_sha256 -cne $package.sha256 -or
        @($manifest.files).Count -ne $selection.file_count) {
        Stop-Setup 'The install manifest does not match the requested pinned package and model.' 'Use the matching -Model/-Root or reinstall into a new root.'
    }
    return $manifest
}

function Quote-Argument([string]$value) {
    if ($value.Contains('"')) {
        Stop-Setup 'A command path contains an unsupported quote character.' 'Choose a simple local -Root path.'
    }
    return '"' + $value + '"'
}

try {
    if ($env:OS -ne 'Windows_NT') {
        Stop-Setup 'This setup command supports Windows only.' 'Use the pinned Linux OVMS GPU image through a separate Linux setup.'
    }
    $pins = Get-ModelPins
    $pinSource = $pins.source
    $selection = $pins.models[$Model]
    $rootPath = Get-RootPath
    $gpuDevice = Get-GpuDevice
    if ($Action -ne 'verify') { Show-Plan $rootPath $gpuDevice }
    if ($Action -eq 'dry-run') { exit 0 }

    if ($Action -eq 'install') {
        if (Test-Path -LiteralPath $rootPath) {
            Stop-Setup 'Install root already exists; this command never overwrites it.' 'Choose a new empty -Root or use -Action serve after a completed install.'
        }
        $hf = Get-Command hf -ErrorAction SilentlyContinue
        if ($null -eq $hf) {
            Stop-Setup 'The Hugging Face hf CLI is missing.' "Install huggingface_hub==$($package.hf_version), then rerun this install command."
        }
        $hfVersion = (& $hf.Source version 2>&1 | Out-String).Trim()
        if ($LASTEXITCODE -ne 0 -or $hfVersion -cne "version=$($package.hf_version)") {
            Stop-Setup "The hf CLI version is not the pinned version $($package.hf_version)." "Install huggingface_hub==$($package.hf_version), then rerun this install command."
        }
        Assert-EnoughDisk $rootPath
        $files = @(Get-PinnedModelMetadata)

        $parent = Split-Path -Parent $rootPath
        if (-not (Test-Path -LiteralPath $parent)) {
            $null = New-Item -ItemType Directory -Path $parent -Force -ErrorAction Stop
        }
        $null = New-Item -ItemType Directory -Path $rootPath -ErrorAction Stop
        $zipPath = Join-Path $rootPath 'ovms.zip'
        Write-Host "Downloading pinned OVMS archive ($($package.bytes) bytes) into $zipPath"
        Invoke-WebRequest -Uri $package.url -OutFile $zipPath -MaximumRedirection 5 -ErrorAction Stop
        Assert-Package $rootPath

        Add-Type -AssemblyName System.IO.Compression
        $archive = [System.IO.Compression.ZipFile]::OpenRead($zipPath)
        try {
            $entries = @($archive.Entries)
            $unpacked = [long](($entries | Measure-Object -Property Length -Sum).Sum)
            if ($entries.Count -ne $package.entries -or $unpacked -ne $package.extracted_bytes) {
                Stop-Setup 'The OVMS archive layout differs from the pinned specification.' 'Do not extract it; inspect the download and retry in a fresh root.'
            }
            foreach ($entry in $entries) {
                if (-not $entry.FullName.StartsWith('ovms/') -or
                    $entry.FullName -match '(^|/)\.\.($|/)' -or
                    $entry.FullName.Contains('\')) {
                    Stop-Setup 'The OVMS archive contains an unsafe path.' 'Do not extract it; inspect the package.'
                }
            }
        } finally {
            $archive.Dispose()
        }
        Expand-Archive -LiteralPath $zipPath -DestinationPath $rootPath -ErrorAction Stop
        Assert-ExtractedPackage $rootPath

        $modelPath = Join-Path $rootPath 'model'
        $stdoutPath = Join-Path $rootPath 'download.stdout.log'
        $stderrPath = Join-Path $rootPath 'download.stderr.log'
        Write-Host "Downloading one pinned model ($($selection.bytes) bytes, $($selection.file_count) files) into $modelPath"
        $hfArgs = @('download', $selection.repository, '--revision', $selection.revision,
                    '--local-dir', (Quote-Argument $modelPath), '--max-workers', '1')
        $previousHfHome = $env:HF_HOME
        $previousHfXetCache = $env:HF_XET_CACHE
        try {
            $env:HF_HOME = Join-Path $rootPath 'hf-home'
            $env:HF_XET_CACHE = Join-Path $rootPath 'hf-home\xet'
            $download = Start-Process -FilePath $hf.Source -ArgumentList $hfArgs -WindowStyle Hidden `
                -WorkingDirectory $rootPath -RedirectStandardOutput $stdoutPath `
                -RedirectStandardError $stderrPath -PassThru -Wait -ErrorAction Stop
        } finally {
            $env:HF_HOME = $previousHfHome
            $env:HF_XET_CACHE = $previousHfXetCache
        }
        if ($download.ExitCode -ne 0) {
            Stop-Setup "Pinned model download failed with exit code $($download.ExitCode); details are in $stderrPath." 'Check network access or hf authentication, then choose a fresh root.'
        }
        Assert-ModelFiles $rootPath $files

        $manifest = [ordered]@{
            schema = 1
            package_version = $package.version
            package_sha256 = $package.sha256
            model = $Model
            model_repository = $selection.repository
            model_revision = $selection.revision
            model_id = $selection.served_name
            files = $files
        }
        $manifestPath = Join-Path $rootPath 'install.json'
        $manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifestPath -Encoding UTF8 -NoNewline
        [ordered]@{status='installed'; root=$rootPath; model=$Model; manifest=$manifestPath} | ConvertTo-Json
        exit 0
    }

    $manifest = Get-InstalledManifest $rootPath
    Assert-Package $rootPath
    Assert-ExtractedPackage $rootPath
    Assert-ModelFiles $rootPath @($manifest.files)
    if ($Action -eq 'verify') {
        [ordered]@{
            status = 'verified'
            model = $Model
            model_id = $selection.id
            provider_model = $selection.served_name
            root = $rootPath
            package_sha256 = $package.sha256
            model_revision = $selection.revision
        } | ConvertTo-Json
        exit 0
    }
    if ($Port -eq $GrpcPort) {
        Stop-Setup 'The REST and gRPC ports must differ.' 'Pass distinct -Port and -GrpcPort values.'
    }
    foreach ($boundPort in @($Port, $GrpcPort)) {
        $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $boundPort)
        try {
            $listener.Start()
        } catch {
            Stop-Setup "Loopback port $boundPort is already in use; no server was started." 'Choose a free port or inspect the existing service without stopping it.'
        } finally {
            $listener.Stop()
        }
    }

    $setupPath = Join-Path $rootPath 'ovms\setupvars.ps1'
    . $setupPath
    $exePath = Join-Path $rootPath 'ovms\ovms.exe'
    $modelPath = Join-Path $rootPath 'model'
    $stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')
    $stdoutPath = Join-Path $rootPath "serve-$stamp.stdout.log"
    $stderrPath = Join-Path $rootPath "serve-$stamp.stderr.log"
    if ((Test-Path -LiteralPath $stdoutPath) -or (Test-Path -LiteralPath $stderrPath)) {
        Stop-Setup 'A server log name already exists; no server was started.' 'Retry after the next timestamp or choose a new root.'
    }
    $serverArgs = @('--model_path', (Quote-Argument $modelPath), '--model_name', $selection.served_name,
                    '--task', 'text_generation', '--target_device', $gpuDevice,
                    '--rest_port', [string]$Port, '--rest_bind_address', '127.0.0.1',
                    '--port', [string]$GrpcPort, '--grpc_bind_address', '127.0.0.1',
                    '--log_level', 'INFO')
    if ($null -ne $selection.tool_parser) {
        $serverArgs += @('--tool_parser', $selection.tool_parser)
    }
    $server = Start-Process -FilePath $exePath -ArgumentList $serverArgs -WindowStyle Hidden `
        -WorkingDirectory $rootPath -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath -PassThru -ErrorAction Stop

    $ready = $false
    $deadline = [DateTime]::UtcNow.AddSeconds($ReadyTimeoutSeconds)
    do {
        if ($server.HasExited) {
            Stop-Setup "OVMS exited with code $($server.ExitCode); logs: $stdoutPath and $stderrPath." 'Inspect the logs and verify the GPU driver, then retry without changing the pinned model.'
        }
        try {
            $result = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/models" -TimeoutSec 3 -ErrorAction Stop
            $names = @($result.data | ForEach-Object { $_.id })
            if ($names -ccontains $selection.served_name) { $ready = $true }
        } catch {
            # A loading model has no ready endpoint yet. The process and logs remain inspectable.
        }
        if (-not $ready) { Start-Sleep -Seconds 2 }
    } while (-not $ready -and [DateTime]::UtcNow -lt $deadline)
    if (-not $ready) {
        Stop-Setup "OVMS process $($server.Id) is still running but did not become ready in $ReadyTimeoutSeconds seconds; logs: $stdoutPath and $stderrPath." 'Inspect that process and its logs; do not launch a second server on the same port.'
    }
    [ordered]@{
        status = 'ready'
        pid = $server.Id
        model_id = $selection.served_name
        gpu_device = $gpuDevice
        models_url = "http://127.0.0.1:$Port/v1/models"
        chat_endpoint = "http://127.0.0.1:$Port/v1/chat/completions"
        stdout_log = $stdoutPath
        stderr_log = $stderrPath
    } | ConvertTo-Json
    exit 0
} catch {
    Write-Error "setup_ovms failed: $($_.Exception.Message)" -ErrorAction Continue
    exit 1
}
