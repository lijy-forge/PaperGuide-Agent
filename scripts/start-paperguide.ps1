<#
.SYNOPSIS
    Start the local PaperGuide Host, API, and Dashboard in separate windows.

.DESCRIPTION
    This launcher intentionally reads provider credentials only from the current
    process environment or the git-ignored project .env file. It never writes,
    prints, or persists credentials.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\start-paperguide.ps1

.EXAMPLE
    .\scripts\start-paperguide.ps1 -NoDashboard -NoBrowser
#>

[CmdletBinding()]
param(
    [switch]$Restart,
    [switch]$NoDashboard,
    [switch]$NoBrowser
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$dashboardRoot = Join-Path $projectRoot "paperguide-dashboard"

function Import-LocalDotEnv {
    param([Parameter(Mandatory)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }

    foreach ($line in Get-Content -LiteralPath $Path) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) {
            continue
        }
        if ($trimmed -notmatch "^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$") {
            continue
        }
        $name = $Matches[1]
        $value = $Matches[2].Trim()
        if (
            $value.Length -ge 2 -and
            (($value.StartsWith('"') -and $value.EndsWith('"')) -or
             ($value.StartsWith("'") -and $value.EndsWith("'")))
        ) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        [Environment]::SetEnvironmentVariable($name, $value, "Process")
    }
}

function Test-ListeningPort {
    param([Parameter(Mandatory)][int]$Port)

    return [bool](
        Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    )
}

function Test-PaperGuideHostRunning {
    try {
        return [bool](
            Get-CimInstance Win32_Process -ErrorAction Stop |
                Where-Object { $_.CommandLine -match "paperguide\.runtime\s+server\s+start" }
        )
    }
    catch {
        # The API readiness endpoint will still report a missing Host. Do not
        # make process-inspection permissions a launch blocker.
        return $false
    }
}

function Get-PaperGuideProcesses {
    $escapedRoot = [regex]::Escape($projectRoot)
    try {
        return @(
            Get-CimInstance Win32_Process -ErrorAction Stop |
                Where-Object {
                    $_.CommandLine -and
                    $_.CommandLine -match $escapedRoot -and
                    (
                        $_.CommandLine -match "paperguide\.runtime\s+server\s+start" -or
                        $_.CommandLine -match 'python(?:\.exe)?["'']?\s+-m\s+paperguide\.api' -or
                        $_.CommandLine -match "paperguide-dashboard.*(?:npm\s+run\s+dev|vite)"
                    )
                }
        )
    }
    catch {
        throw "Unable to inspect existing PaperGuide processes. Run PowerShell with permission to query local processes."
    }
}

function Restart-PaperGuideProcesses {
    $processes = @(Get-PaperGuideProcesses)
    if (-not $processes) {
        return
    }

    # Resolve exact project-owned processes before stopping anything. This
    # avoids touching unrelated Python, Node, or PowerShell sessions.
    $targetProcessIds = @($processes | Select-Object -ExpandProperty ProcessId -Unique)
    foreach ($targetProcessId in $targetProcessIds) {
        try {
            [System.Diagnostics.Process]::GetProcessById(
                [int]$targetProcessId
            ).Kill()
        }
        catch [System.ArgumentException] {
            # A parent process may already have terminated its child.
        }
    }
    # The persistent host protects ownership with a short heartbeat TTL.
    # A forced local restart must let that lease expire before the replacement
    # Host attempts to acquire it, otherwise it exits as AlreadyRunning.
    Start-Sleep -Seconds 6
    Write-Host "Stopped existing PaperGuide processes."
}

function Start-PaperGuideProcess {
    param(
        [Parameter(Mandatory)][string]$Title,
        [Parameter(Mandatory)][string]$Command
    )

    $escapedRoot = $projectRoot.Replace("'", "''")
    $windowCommand = "Set-Location -LiteralPath '$escapedRoot'; `$Host.UI.RawUI.WindowTitle = '$Title'; $Command"
    Start-Process -FilePath "powershell.exe" -ArgumentList @(
        "-NoExit",
        "-ExecutionPolicy", "Bypass",
        "-Command", $windowCommand
    ) | Out-Null
}

if (-not (Test-Path -LiteralPath $python)) {
    throw "PaperGuide virtual environment was not found. Create .venv before starting."
}

Import-LocalDotEnv -Path (Join-Path $projectRoot ".env")

if ($Restart) {
    Restart-PaperGuideProcesses
}

if (-not $env:PAPERGUIDE_LLM_PROVIDER) {
    $env:PAPERGUIDE_LLM_PROVIDER = "deepseek"
}
if (-not $env:PAPERGUIDE_MODEL_NAME) {
    $env:PAPERGUIDE_MODEL_NAME = "deepseek-v4-flash"
}
if (-not $env:PAPERGUIDE_EXPORT_DIRECTORY) {
    $env:PAPERGUIDE_EXPORT_DIRECTORY = "./runtime-data/artifacts"
}

if ($env:PAPERGUIDE_LLM_PROVIDER -eq "deepseek" -and -not $env:DEEPSEEK_API_KEY) {
    throw "DEEPSEEK_API_KEY is missing. Add it to the git-ignored .env file or the current PowerShell environment."
}

if (-not (Test-PaperGuideHostRunning)) {
    Start-PaperGuideProcess -Title "PaperGuide Host" -Command "& '$python' -m paperguide.runtime server start"
    Write-Host "Started PaperGuide Host."
}
else {
    Write-Host "PaperGuide Host is already running."
}

if (-not (Test-ListeningPort -Port 8000)) {
    Start-PaperGuideProcess -Title "PaperGuide API" -Command "& '$python' -m paperguide.api"
    Write-Host "Started PaperGuide API at http://127.0.0.1:8000."
}
else {
    Write-Host "PaperGuide API is already listening on port 8000."
}

if (-not $NoDashboard) {
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        throw "npm was not found. Install Node.js LTS before starting the Dashboard."
    }
    if (-not (Test-Path -LiteralPath (Join-Path $dashboardRoot "node_modules"))) {
        Write-Host "Installing Dashboard dependencies (first run only)..."
        Push-Location $dashboardRoot
        try {
            npm install
        }
        finally {
            Pop-Location
        }
    }
    if (-not (Test-ListeningPort -Port 5173)) {
        # Vite captures VITE_* variables when it starts. PaperGuide's local API
        # always listens on 8000, so do not inherit an incomplete root value
        # such as "http://localhost" without its API port.
        $env:VITE_PAPERGUIDE_API_BASE_URL = "http://127.0.0.1:8000"
        $escapedDashboardRoot = $dashboardRoot.Replace("'", "''")
        $dashboardCommand = "Set-Location -LiteralPath '$escapedDashboardRoot'; `$Host.UI.RawUI.WindowTitle = 'PaperGuide Dashboard'; npm run dev"
        Start-Process -FilePath "powershell.exe" -ArgumentList @(
            "-NoExit",
            "-ExecutionPolicy", "Bypass",
            "-Command", $dashboardCommand
        ) | Out-Null
        Write-Host "Started PaperGuide Dashboard at http://127.0.0.1:5173."
    }
    else {
        Write-Host "PaperGuide Dashboard is already listening on port 5173."
    }
}

if (-not $NoBrowser -and -not $NoDashboard) {
    Start-Process "http://127.0.0.1:5173"
}

Write-Host "PaperGuide launch request completed."
