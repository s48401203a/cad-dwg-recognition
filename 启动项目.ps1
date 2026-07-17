param(
    [int]$Port = 8000,
    [int]$MaxPort = 8020,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new() } catch {}

$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Join-Path $RootDir "backend"
$StatePath = Join-Path $RootDir ".cad-server.json"
$LogDir = Join-Path $BackendDir "logs"
$ShareConfigPath = Join-Path $RootDir "frontend\share-config.js"

function Find-Python {
    $candidates = @(
        @{ File = (Join-Path $RootDir ".venv\Scripts\python.exe"); Args = @() }
    )

    foreach ($candidate in $candidates) {
        if ((Test-Path -LiteralPath $candidate.File) -and (Test-PythonCandidate $candidate.File $candidate.Args)) {
            return $candidate
        }
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python -and (Test-PythonCandidate $python.Source @())) {
        return @{ File = $python.Source; Args = @() }
    }

    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        foreach ($args in @(@("-3.12"), @("-3.11"), @("-3.10"), @("-3"))) {
            if (Test-PythonCandidate $py.Source $args) {
                return @{ File = $py.Source; Args = $args }
            }
        }
    }

    throw "Python was not found. Please add python to PATH or create a .venv in the project root."
}

function Test-PythonCandidate([string]$FilePath, [string[]]$Arguments) {
    try {
        & $FilePath @Arguments -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" *> $null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

function Get-PortListener([int]$CheckPort) {
    Get-NetTCPConnection -LocalPort $CheckPort -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
}

function Test-CadService([int]$CheckPort) {
    try {
        $healthUrl = "http://127.0.0.1:{0}/api/health" -f $CheckPort
        $health = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 2
        return [bool]$health.ok
    } catch {
        return $false
    }
}

function Open-CadBrowser([string]$Url) {
    if (-not $NoBrowser) {
        Start-Process $Url | Out-Null
    }
}

function Get-LanIp {
    try {
        $ip = Get-NetIPConfiguration |
            Where-Object { $_.IPv4DefaultGateway -and $_.IPv4Address } |
            Select-Object -ExpandProperty IPv4Address -First 1 |
            Select-Object -ExpandProperty IPAddress -First 1
        if ($ip) { return $ip }
    } catch {}
    try {
        $ip = Get-NetIPAddress -AddressFamily IPv4 |
            Where-Object {
                $_.IPAddress -notlike "127.*" -and
                $_.IPAddress -notlike "169.254.*" -and
                $_.PrefixOrigin -ne "WellKnown"
            } |
            Sort-Object InterfaceMetric |
            Select-Object -ExpandProperty IPAddress -First 1
        if ($ip) { return $ip }
    } catch {}
    return "127.0.0.1"
}

function Update-ShareConfig {
    $lanIp = Get-LanIp
    $updatedAt = Get-Date -Format "yyyy-MM-dd"
    $content = @"
window.CAD3D_SHARE = {
  host: "$lanIp",
  hosts: ["$lanIp"],
  updatedAt: "$updatedAt"
};
"@
    Set-Content -LiteralPath $ShareConfigPath -Value $content -Encoding UTF8
    Write-Host "Share link host refreshed: $lanIp"
}

if (-not (Test-Path -LiteralPath (Join-Path $BackendDir "main.py"))) {
    throw "backend\main.py was not found. Please run this script from the project root. Root: $RootDir"
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Update-ShareConfig

$SelectedPort = $Port
while ($SelectedPort -le $MaxPort) {
    $listener = Get-PortListener $SelectedPort
    if (-not $listener) {
        break
    }

    if (Test-CadService $SelectedPort) {
        $url = "http://127.0.0.1:{0}" -f $SelectedPort
        Write-Host "CAD service is already running: $url"
        Open-CadBrowser $url
        return
    }

    Write-Host "Port $SelectedPort is occupied by another program. Trying the next port..."
    $SelectedPort += 1
}

if ($SelectedPort -gt $MaxPort) {
    throw "No available port from $Port to $MaxPort. Please close the program occupying these ports and try again."
}

$pythonInfo = Find-Python
$pythonExe = $pythonInfo.File
$pythonBaseArgs = @($pythonInfo.Args)

Write-Host "Checking Python dependencies..."
& $pythonExe @pythonBaseArgs -c "import fastapi, uvicorn, ezdxf, multipart, websockets, yaml"
if ($LASTEXITCODE -ne 0) {
    throw "Python dependencies are incomplete. Please run install-env.ps1."
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$stdoutLog = Join-Path $LogDir "server-$timestamp.out.log"
$stderrLog = Join-Path $LogDir "server-$timestamp.err.log"
$serverArgs = @($pythonBaseArgs + @("-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "$SelectedPort"))

Write-Host "Starting CAD service..."
$process = Start-Process `
    -FilePath $pythonExe `
    -ArgumentList $serverArgs `
    -WorkingDirectory $BackendDir `
    -WindowStyle Hidden `
    -PassThru `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog

$url = "http://127.0.0.1:{0}" -f $SelectedPort
$state = [ordered]@{
    pid = $process.Id
    port = $SelectedPort
    url = $url
    root = $RootDir
    backend = $BackendDir
    stdout_log = $stdoutLog
    stderr_log = $stderrLog
    started_at = (Get-Date).ToString("s")
}
$state | ConvertTo-Json | Set-Content -LiteralPath $StatePath -Encoding UTF8

for ($i = 0; $i -lt 40; $i++) {
    if (Test-CadService $SelectedPort) {
        $listener = Get-PortListener $SelectedPort
        if ($listener -and $listener.OwningProcess) {
            $state.pid = [int]$listener.OwningProcess
            $state | ConvertTo-Json | Set-Content -LiteralPath $StatePath -Encoding UTF8
        }
        Write-Host "Started successfully: $url"
        Write-Host "PID: $($state.pid)"
        Write-Host "Log file: $stdoutLog"
        Open-CadBrowser $url
        return
    }
    Start-Sleep -Milliseconds 500
}

Write-Host "Service startup timed out. Please check logs:"
Write-Host "stdout: $stdoutLog"
Write-Host "stderr: $stderrLog"
exit 1
