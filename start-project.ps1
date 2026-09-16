# 启动 CAD 读取器（Windows）。
#
# 默认走仓库内自包含启动器 `backend\server.py`：它会挑选空闲端口、生成访问令牌、
# 写出运行期状态（并额外写出兼容本脚本族系的 .cad-server.json），并且**不会**以
# 无鉴权状态绑定到局域网地址。
param(
    [int]$Port = 8000,
    [int]$MaxPort = 8020,
    [switch]$NoBrowser,
    [switch]$SkipProjectApps,
    [switch]$SyncProjectPackages,
    [switch]$Lan
)

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new() } catch {}

$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Join-Path $RootDir "backend"
$StateFileName = if ($env:CAD_SERVER_STATE_NAME) { ".{0}.json" -f $env:CAD_SERVER_STATE_NAME } else { ".cad-server.json" }
$StatePath = Join-Path $RootDir $StateFileName
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

function Invoke-ProjectPackageSync([hashtable]$PythonInfo) {
    $syncScript = Join-Path $RootDir "tools\sync_project_packages.py"
    if (-not (Test-Path -LiteralPath $syncScript)) {
        return
    }
    $pythonExe = $PythonInfo.File
    $pythonBaseArgs = @($PythonInfo.Args)
    Write-Host "Syncing CAD project packages..."
    & $pythonExe @pythonBaseArgs $syncScript
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "CAD project package sync failed. Exit code: $LASTEXITCODE"
    }
}

function Start-ProjectApps([hashtable]$PythonInfo) {
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
            $pythonExe = $PythonInfo.File
            $pythonBaseArgs = @($PythonInfo.Args)
            Write-Host "Waking project app: $($app.Name)"
            & $pythonExe @pythonBaseArgs $serverControl start
            continue
        }
        $script = Get-ChildItem -LiteralPath $app.FullName -Filter "启动-*.ps1" -ErrorAction SilentlyContinue |
            Sort-Object Name |
            Select-Object -First 1
        if ($script) {
            Write-Host "Waking project app: $($app.Name)"
            & $script.FullName
        }
    }
}

function Invoke-ProjectWakeup([hashtable]$PythonInfo) {
    if ($SyncProjectPackages) {
        Invoke-ProjectPackageSync $PythonInfo
    }
    Start-ProjectApps $PythonInfo
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
        try {
            $pythonInfo = Find-Python
            Invoke-ProjectWakeup $pythonInfo
        } catch {
            Write-Warning "Project wakeup skipped: $($_.Exception.Message)"
        }
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

$serverLauncher = Join-Path $BackendDir "server.py"
if (-not (Test-Path -LiteralPath $serverLauncher)) {
    throw "backend\server.py was not found. It ships with the repository; please re-check the checkout."
}

try {
    Push-Location $BackendDir
    & $pythonExe @pythonBaseArgs -m log_retention | Out-Null
} catch {
    Write-Warning "Log retention skipped: $($_.Exception.Message)"
} finally {
    Pop-Location
}

# 由 backend\server.py 负责：挑端口、生成令牌、写状态、按需绑定局域网。
$launcherArgs = @(
    $pythonBaseArgs +
    @($serverLauncher, "--port", "$SelectedPort", "--legacy-state") +
    $(if ($Lan) { @("--lan") } else { @() }) +
    $(if ($NoBrowser) { @("--no-open") } else { @() })
)

# Start-Process 会把 -ArgumentList 数组用空格拼接，因此含空格的路径必须显式加引号。
$quotedArgs = $launcherArgs | ForEach-Object { '"' + ([string]$_ -replace '"', '\"') + '"' }

Write-Host "Starting CAD service (backend\server.py)..."
$process = Start-Process `
    -FilePath $pythonExe `
    -ArgumentList $quotedArgs `
    -WorkingDirectory $BackendDir `
    -WindowStyle Hidden `
    -PassThru

# 等待启动器写出状态（含端口与访问令牌提示），再轮询健康检查。
$url = $null
for ($i = 0; $i -lt 60; $i++) {
    if (Test-Path -LiteralPath $StatePath) {
        try {
            $state = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json
            if ($state.port) {
                $url = $state.url
                if (Test-CadService ([int]$state.port)) { break }
            }
        } catch {}
    }
    Start-Sleep -Milliseconds 500
}

if (-not $url) {
    $url = "http://127.0.0.1:{0}" -f $SelectedPort
}

if (Test-CadService $SelectedPort) {
    Write-Host "Started successfully: $url"
    if ($Lan) {
        Write-Host "LAN mode is ON: an access token was generated and printed by the launcher."
        Write-Host "Unauthenticated visitors on the LAN cannot read projects or export files."
    }
    Invoke-ProjectWakeup $pythonInfo
    if (-not $NoBrowser) {
        Open-CadBrowser $url
    }
    return
}

Write-Host "Service startup timed out. Please check the console output above and:"
Write-Host "  $StatePath"
Write-Host "  运行 backup 前的日志目录: backend\logs"
exit 1
