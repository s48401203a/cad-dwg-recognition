param(
    [int]$Port = 0
)

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new() } catch {}

$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$StatePath = Join-Path $RootDir ".cad-server.json"
$Stopped = $false

function Test-CadService([int]$CheckPort) {
    try {
        $healthUrl = "http://127.0.0.1:{0}/api/health" -f $CheckPort
        $health = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 2
        return [bool]$health.ok
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

if ($Port -gt 0) {
    $Stopped = Stop-CadPort $Port
    if (-not $Stopped) {
        Write-Host "No CAD service was found on port $Port."
    }
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
