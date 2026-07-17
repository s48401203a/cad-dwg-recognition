param(
    [string]$Label = "manual-snapshot"
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$SafeLabel = ($Label -replace '[\\/:*?"<>|]', '-').Trim()
if (-not $SafeLabel) {
    $SafeLabel = "manual-snapshot"
}

$BackupRoot = Join-Path $Root "backups"
$BackupName = "v$Timestamp-$SafeLabel"
$Destination = Join-Path $BackupRoot $BackupName

New-Item -ItemType Directory -Force -Path $Destination | Out-Null

$ExcludeTopLevel = @(
    ".git",
    ".venv",
    ".codex-tmp",
    "backups",
    "exports",
    "output"
)

Get-ChildItem -LiteralPath $Root -Force | ForEach-Object {
    if ($ExcludeTopLevel -contains $_.Name) {
        return
    }
    $target = Join-Path $Destination $_.Name
    Copy-Item -LiteralPath $_.FullName -Destination $target -Recurse -Force
}

$RemoveDirs = @("__pycache__", ".pytest_cache", "node_modules")
foreach ($dirName in $RemoveDirs) {
    Get-ChildItem -LiteralPath $Destination -Recurse -Force -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -eq $dirName } |
        Remove-Item -Recurse -Force
}

$LogDir = Join-Path $Destination "backend\logs"
if (Test-Path -LiteralPath $LogDir) {
    Remove-Item -LiteralPath $LogDir -Recurse -Force
}

$GitStatus = @()
try {
    $GitStatus = git -C $Root status --short
} catch {
    $GitStatus = @("git status unavailable: $($_.Exception.Message)")
}

$Manifest = [ordered]@{
    backup_name = $BackupName
    created_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
    source_root = $Root
    destination = $Destination
    label = $SafeLabel
    excluded_top_level = $ExcludeTopLevel
    removed_generated_dirs = $RemoveDirs
    removed_paths = @("backend\logs")
    git_status_short = $GitStatus
}

$ManifestPath = Join-Path $Destination "BACKUP_MANIFEST.json"
$Manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $ManifestPath -Encoding UTF8

Write-Host "BACKUP_CREATED=$Destination"
