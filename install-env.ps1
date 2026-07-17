param(
    [switch]$NoWinget,
    [switch]$SkipOda,
    [switch]$RequireOda,
    [switch]$NoPause
)

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new() } catch {}

$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Join-Path $RootDir "backend"
$RequirementsPath = Join-Path $RootDir "requirements.txt"
$VenvDir = Join-Path $RootDir ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$WheelhouseDir = Join-Path $RootDir "wheelhouse"

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message"
}

function Invoke-Checked([string]$FilePath, [string[]]$Arguments, [string]$WorkingDirectory = $RootDir) {
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed: $FilePath $($Arguments -join ' ')"
    }
}

function Test-PythonVersion([string]$FilePath, [string[]]$Arguments) {
    & $FilePath @Arguments -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" *> $null
    return $LASTEXITCODE -eq 0
}

function Get-PythonVersion([string]$FilePath, [string[]]$Arguments) {
    & $FilePath @Arguments -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"
}

function Find-Python {
    $candidates = @()

    if (Test-Path -LiteralPath $VenvPython) {
        $candidates += @{ File = $VenvPython; Args = @() }
    }

    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        $candidates += @{ File = $py.Source; Args = @("-3.12") }
        $candidates += @{ File = $py.Source; Args = @("-3.11") }
        $candidates += @{ File = $py.Source; Args = @("-3.10") }
        $candidates += @{ File = $py.Source; Args = @("-3") }
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        $candidates += @{ File = $python.Source; Args = @() }
    }

    $knownRoots = @(
        "$env:LocalAppData\Programs\Python",
        "$env:ProgramFiles\Python312",
        "$env:ProgramFiles\Python311",
        "$env:ProgramFiles\Python310"
    )
    foreach ($root in $knownRoots) {
        if (Test-Path -LiteralPath $root) {
            Get-ChildItem -LiteralPath $root -Recurse -Filter python.exe -ErrorAction SilentlyContinue |
                ForEach-Object { $candidates += @{ File = $_.FullName; Args = @() } }
        }
    }

    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate.File) {
            if (Test-PythonVersion $candidate.File $candidate.Args) {
                return $candidate
            }
        }
    }
    return $null
}

function Install-PythonWithWinget {
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) {
        return $false
    }

    Write-Step "Installing Python 3.12 with winget"
    & $winget.Source install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
    return $LASTEXITCODE -eq 0
}

function Find-OdaFileConverter {
    if ($env:ODA_FILE_CONVERTER -and (Test-Path -LiteralPath $env:ODA_FILE_CONVERTER)) {
        return (Resolve-Path -LiteralPath $env:ODA_FILE_CONVERTER).Path
    }

    $roots = @()
    if ($env:ProgramFiles) {
        $roots += Join-Path $env:ProgramFiles "ODA"
    }
    $programFilesX86 = [Environment]::GetEnvironmentVariable("ProgramFiles(x86)")
    if ($programFilesX86) {
        $roots += Join-Path $programFilesX86 "ODA"
    }
    $matches = @()
    foreach ($root in $roots) {
        if (Test-Path -LiteralPath $root) {
            $matches += Get-ChildItem -LiteralPath $root -Recurse -Filter ODAFileConverter.exe -ErrorAction SilentlyContinue
        }
    }
    if ($matches.Count -gt 0) {
        return ($matches | Sort-Object FullName -Descending | Select-Object -First 1).FullName
    }
    return $null
}

function Install-OdaWithWinget {
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) {
        return $false
    }

    Write-Step "Installing ODA File Converter with winget"
    & $winget.Source install -e --id OpenDesignAlliance.ODAFileConverter --accept-package-agreements --accept-source-agreements
    return $LASTEXITCODE -eq 0
}

if (-not (Test-Path -LiteralPath (Join-Path $BackendDir "main.py"))) {
    throw "backend\main.py was not found. Please run this script from the project root."
}
if (-not (Test-Path -LiteralPath $RequirementsPath)) {
    throw "requirements.txt was not found."
}

Write-Step "Checking Python 3.10+"
$pythonInfo = Find-Python
if (-not $pythonInfo -and -not $NoWinget) {
    [void](Install-PythonWithWinget)
    $pythonInfo = Find-Python
}
if (-not $pythonInfo) {
    throw "Python 3.10+ was not found. Install Python 3.10 or newer, or rerun this script on a computer with internet and winget."
}
Write-Host "Python: $(Get-PythonVersion $pythonInfo.File $pythonInfo.Args)"

Write-Step "Creating local virtual environment"
if ((Test-Path -LiteralPath $VenvPython) -and -not (Test-PythonVersion $VenvPython @())) {
    Write-Warning "Existing .venv is invalid for this computer. Recreating it."
    Remove-Item -LiteralPath $VenvDir -Recurse -Force
}
if (-not (Test-Path -LiteralPath $VenvPython)) {
    Invoke-Checked $pythonInfo.File @($pythonInfo.Args + @("-m", "venv", $VenvDir))
}
Write-Host "Virtual environment: .venv"

Write-Step "Installing Python packages"
Invoke-Checked $VenvPython @("-m", "pip", "install", "--upgrade", "pip")
if (Test-Path -LiteralPath $WheelhouseDir) {
    Write-Host "Using local wheelhouse folder."
    Invoke-Checked $VenvPython @("-m", "pip", "install", "--no-index", "--find-links", $WheelhouseDir, "-r", $RequirementsPath)
} else {
    Invoke-Checked $VenvPython @("-m", "pip", "install", "-r", $RequirementsPath)
}

Write-Step "Validating Python packages"
Invoke-Checked $VenvPython @("-c", "import aiofiles, fastapi, uvicorn, ezdxf, multipart, websockets, yaml; print('Python dependencies OK')")

if (-not $SkipOda) {
    Write-Step "Checking ODA File Converter for DWG support"
    $odaPath = Find-OdaFileConverter
    if (-not $odaPath -and -not $NoWinget) {
        [void](Install-OdaWithWinget)
        $odaPath = Find-OdaFileConverter
    }

    if ($odaPath) {
        $env:ODA_FILE_CONVERTER = $odaPath
        [Environment]::SetEnvironmentVariable("ODA_FILE_CONVERTER", $odaPath, "User")
        Write-Host "ODA File Converter: $odaPath"
    } else {
        $message = "ODA File Converter was not found. DXF can be parsed, but DWG upload requires ODA File Converter."
        if ($RequireOda) {
            throw $message
        }
        Write-Warning $message
    }
}

Write-Step "Environment is ready"
Write-Host "Next step: run start-project.ps1 or double-click the startup BAT file."

if (-not $NoPause) {
    Write-Host ""
    Write-Host "Press any key to close this window."
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
}
