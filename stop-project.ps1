param(
    [int]$Port = 0,
    [switch]$SkipProjectApps
)

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new() } catch {}

$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$StateFileName = if ($env:CAD_SERVER_STATE_NAME) { ".{0}.json" -f $env:CAD_SERVER_STATE_NAME } else { ".cad-server.json" }
$StatePath = Join-Path $RootDir $StateFileName
$Stopped = $false

function Test-CadService([int]$CheckPort) {
    try {
        $healthUrl = "http://127.0.0.1:{0}/api/health" -f $CheckPort
        $health = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 2
        if (-not [bool]$health.ok) {
            return $false
        }
        $scopeProjectId = $env:CAD_SCOPE_PROJECT_ID
        if ($scopeProjectId) {
            return [string]$health.scope_project_id -eq [string]$scopeProjectId
        }
        return -not [string]$health.scope_project_id
    } catch {
        return $false
    }
}

function Stop-CadPort([int]$CheckPort) {
    if (-not (Test-CadService $CheckPort)) {
        return $false
    }
    $listener = Get-NetTCPConnection -LocalPort $CheckPort -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $listener) {
        return $false
    }
    Stop-Process -Id $listener.OwningProcess -Force
    Write-Host "Stopped CAD service on port $CheckPort. PID: $($listener.OwningProcess)"
    return $true
}

function Stop-ProjectApps {
    if ($SkipProjectApps) {
        return
    }
    $packagesRoot = Join-Path $RootDir "projects"
    if (-not (Test-Path -LiteralPath $packagesRoot)) {
        return
    }
    $apps = Get-ChildItem -LiteralPath $packagesRoot -Directory -ErrorAction SilentlyContinue |
        Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName "studio.json") }
    foreach ($app in $apps) {
        $serverControl = Join-Path $app.FullName "server_control.py"
        if (Test-Path -LiteralPath $serverControl) {
            $pythonExe = Join-Path $RootDir ".venv\Scripts\python.exe"
            if (-not (Test-Path -LiteralPath $pythonExe)) {
                $pythonExe = "python"
            }
            Write-Host "Stopping project app: $($app.Name)"
            & $pythonExe $serverControl stop
            continue
        }
        $script = Get-ChildItem -LiteralPath $app.FullName -Filter "停止-*.ps1" -ErrorAction SilentlyContinue |
            Sort-Object Name |
            Select-Object -First 1
        if ($script) {
            Write-Host "Stopping project app: $($app.Name)"
            & $script.FullName
        }
    }
}

if ($Port -gt 0) {
    $Stopped = Stop-CadPort $Port
    if (-not $Stopped) {
        Write-Host "No CAD service was found on port $Port."
    }
    Stop-ProjectApps
    return
}

if (Test-Path -LiteralPath $StatePath) {
    try {
        $state = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json
        if ($state.pid) {
            $process = Get-Process -Id ([int]$state.pid) -ErrorAction SilentlyContinue
            if ($process) {
                Stop-Process -Id $process.Id -Force
                Write-Host "Stopped CAD service. PID: $($process.Id)"
                $Stopped = $true
            }
        }
        if ($state.port) {
            $portStopped = Stop-CadPort ([int]$state.port)
            $Stopped = $Stopped -or $portStopped
        }
    } finally {
        Remove-Item -LiteralPath $StatePath -Force -ErrorAction SilentlyContinue
    }
}

if (-not $Stopped) {
    foreach ($candidate in 8000..8020) {
        if (Stop-CadPort $candidate) {
            $Stopped = $true
            break
        }
    }
}

if (-not $Stopped) {
    Write-Host "No running CAD service was found."
}

Stop-ProjectApps
