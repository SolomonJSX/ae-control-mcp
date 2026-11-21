<#
.SYNOPSIS
    Installs the ae-control Antigravity plugin into ~/.gemini/config/plugins/ae-control/
    and configures mcp_config.json to launch the server directly from this repo's .venv.
#>
param(
    [string]$AeExePath = "",
    [string]$AeRenderPath = "",
    [switch]$SkipUvSync
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PluginSrc = Join-Path $RepoRoot "plugin"
$PluginDst = Join-Path $env:USERPROFILE ".gemini\config\plugins\ae-control"
$VenvExe = Join-Path $RepoRoot ".venv\Scripts\ae-control-mcp.exe"

$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$venvHealthy = $false
if ((Test-Path $VenvExe) -and (Test-Path $VenvPython)) {
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $VenvPython -c "import ae_control_mcp" *> $null
        if ($LASTEXITCODE -eq 0) {
            $venvHealthy = $true
        }
    } catch {
        $venvHealthy = $false
    } finally {
        $ErrorActionPreference = $prevEap
    }
}

if (-not $SkipUvSync -and -not $venvHealthy) {
    if (Test-Path (Join-Path $RepoRoot ".venv")) {
        Write-Host "Existing .venv is broken or incompatible with this PC; recreating..."
        Remove-Item -Recurse -Force (Join-Path $RepoRoot ".venv")
    }
    Write-Host "Running 'uv sync' to create .venv..."
    Push-Location $RepoRoot
    try {
        uv sync
    } finally {
        Pop-Location
    }
}

if (-not (Test-Path $VenvExe)) {
    throw "MCP executable not found at $VenvExe. Run 'uv sync' in $RepoRoot first."
}

# Auto-detect After Effects installation if not explicitly provided (prefer AE 2020)
if (-not $AeExePath) {
    $ae2020 = "C:\Program Files\Adobe\Adobe After Effects 2020\Support Files\AfterFX.exe"
    if (Test-Path $ae2020) {
        $AeExePath = $ae2020
        Write-Host "Detected After Effects 2020: $AeExePath"
    } else {
        $detected = Get-ChildItem "C:\Program Files\Adobe\Adobe After Effects *\Support Files\AfterFX.exe" -ErrorAction SilentlyContinue |
            Sort-Object FullName -Descending |
            Select-Object -First 1
        if ($detected) {
            $AeExePath = $detected.FullName
            Write-Host "Detected AfterFX.exe: $AeExePath"
        } else {
            $AeExePath = $ae2020
            Write-Host "After Effects not detected on this PC; defaulting AE_EXE_PATH to: $AeExePath"
        }
    }
}

if (-not $AeRenderPath) {
    $supportDir = Split-Path $AeExePath -Parent
    $AeRenderPath = Join-Path $supportDir "aerender.exe"
}

New-Item -ItemType Directory -Force -Path $PluginDst | Out-Null
Copy-Item -Recurse -Force (Join-Path $PluginSrc "*") $PluginDst

$mcpConfig = [ordered]@{
    mcpServers = [ordered]@{
        "ae-control-mcp" = [ordered]@{
            command = $VenvExe
            args    = @()
            env     = [ordered]@{
                AE_EXE_PATH    = $AeExePath
                AE_RENDER_PATH = $AeRenderPath
            }
        }
    }
}

$json = $mcpConfig | ConvertTo-Json -Depth 5
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText((Join-Path $PluginDst "mcp_config.json"), $json + "`n", $utf8NoBom)

Write-Host "Installed ae-control plugin to: $PluginDst"
Write-Host "MCP command: $VenvExe"
