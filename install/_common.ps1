# Shared helpers for the BCA robot / panel installers.
# Dot-sourced by install_robot.ps1 and install_panel.ps1. Defining only.

$ErrorActionPreference = 'Stop'

function Test-Admin {
    $principal = New-Object Security.Principal.WindowsPrincipal(
        [Security.Principal.WindowsIdentity]::GetCurrent())
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-RepoRoot {
    param([string]$InstallerDir)
    $root = (Resolve-Path -LiteralPath (Join-Path $InstallerDir '..')).Path
    $configPath = Join-Path $root 'config.json'
    if (-not (Test-Path -LiteralPath $configPath)) {
        $example = Join-Path $root 'config.example.json'
        if (-not (Test-Path -LiteralPath $example)) {
            throw "Could not find the project root above '$InstallerDir' (missing config.json)."
        }
        Copy-Item -LiteralPath $example -Destination $configPath
        Write-Host '   !   config.json created from config.example.json - set robot_token, backoffice and proxy values.' -ForegroundColor Yellow
    }
    return $root
}

function Write-Step {
    param([int]$Number, [int]$Total, [string]$Message)
    Write-Host ''
    Write-Host ("[{0}/{1}] {2}" -f $Number, $Total, $Message) -ForegroundColor Cyan
}

function Write-Ok   { param([string]$Message) Write-Host ('   OK  ' + $Message) -ForegroundColor Green }
function Write-Warn { param([string]$Message) Write-Host ('   !   ' + $Message) -ForegroundColor Yellow }
function Write-Err  { param([string]$Message) Write-Host ('   X   ' + $Message) -ForegroundColor Red }

function Invoke-Native {
    param([string]$Exe, [string[]]$Arguments, [string]$Label)
    Write-Host ("   > {0} {1}" -f $Exe, ($Arguments -join ' ')) -ForegroundColor DarkGray
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw ("{0} failed with exit code {1}." -f $Label, $LASTEXITCODE)
    }
}

function Get-PythonExe {
    $candidates = @()
    try {
        $candidates += (& py -3 -c "import sys; print(sys.executable)" 2>$null)
    } catch { }
    foreach ($name in @('python.exe', 'python3.exe')) {
        $found = Get-Command $name -All -ErrorAction SilentlyContinue |
            Where-Object { $_.Source -notmatch 'WindowsApps' }
        if ($found) { $candidates += $found[0].Source }
    }
    foreach ($c in $candidates) {
        if ($c -and (Test-Path -LiteralPath $c) -and $c -notmatch 'WindowsApps') {
            return (Resolve-Path -LiteralPath $c).Path
        }
    }
    return $null
}

function Install-Python {
    Write-Warn 'Python was not found. Trying to install it with winget...'
    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw 'winget is not available. Install Python 3 from https://www.python.org/downloads/windows/ (tick "Add python.exe to PATH") and run this installer again.'
    }
    & winget install --id Python.Python.3.12 -e --scope user --accept-source-agreements --accept-package-agreements
    Start-Sleep -Seconds 3
    $py = Get-PythonExe
    if (-not $py) {
        throw 'Python was installed but is not visible in this window yet. Close this window and run the installer again.'
    }
    return $py
}

function Resolve-Python {
    param([bool]$AutoInstall = $true)
    $py = Get-PythonExe
    if (-not $py -and $AutoInstall) {
        $py = Install-Python
    }
    if (-not $py) {
        throw 'Python was not found. Install Python 3, then run this installer again.'
    }
    return $py
}

function Ensure-Venv {
    param([string]$RepoRoot, [string]$PythonExe)
    $venvDir = Join-Path $RepoRoot '.venv'
    $venvPython = Join-Path $venvDir 'Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $venvPython)) {
        Write-Host '   Creating the virtual environment (.venv)...' -ForegroundColor DarkGray
        Invoke-Native -Exe $PythonExe -Arguments @('-m', 'venv', $venvDir) -Label 'virtual environment creation'
    } else {
        Write-Host '   Reusing the existing virtual environment (.venv).' -ForegroundColor DarkGray
    }
    & $venvPython -m pip install --upgrade pip --quiet 2>&1 | Out-Host
    return $venvPython
}

function Write-Launcher {
    param([string]$Path, [string]$RepoRoot, [string]$VenvPython, [string]$ScriptRel, [string]$Title)
    $lines = @(
        '@echo off'
        ('title {0}' -f $Title)
        ('cd /d "{0}"' -f $RepoRoot)
        ('"{0}" "{1}"' -f $VenvPython, $ScriptRel)
        'echo.'
        'echo Server stopped. Press any key to close.'
        'pause >nul'
    )
    Set-Content -LiteralPath $Path -Value $lines -Encoding ASCII
}
