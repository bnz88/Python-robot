<#
.SYNOPSIS
    One-click installer for the BCA Robot (the scraper server, api.py).

.DESCRIPTION
    Double-click install_robot.cmd (or run this file). It will:
      1. find Python (and offer to install it with winget if missing);
      2. create an isolated virtual environment (.venv);
      3. install the robot's Python packages;
      4. install the Playwright browser used for backoffice uploads;
      5. verify Google Chrome is present;
      6. prepare the output folder and create run_robot.cmd;
      7. print what to do next.

    Use -Unattended (from an Administrator window) to also register the robot
    and panel to start automatically at logon on an always-on VM.

.PARAMETER SkipPlaywright
    Do not install the Playwright chromium browser (only needed for the
    backoffice upload).

.PARAMETER Unattended
    After installing, run deploy\windows-unattended.ps1 to start the servers at
    logon. Requires an Administrator PowerShell.

.PARAMETER AutoLogonUser
    Passed to the unattended setup to configure auto-login.

.PARAMETER RemoteSubnet
    Passed to the unattended setup as the firewall scope. Default 'LocalSubnet'.
#>
[CmdletBinding()]
param(
    [switch]$SkipPlaywright,
    [switch]$Unattended,
    [string]$AutoLogonUser,
    [string]$RemoteSubnet = 'LocalSubnet'
)

. (Join-Path $PSScriptRoot '_common.ps1')

$root = Get-RepoRoot -InstallerDir $PSScriptRoot
Write-Host '=========================================' -ForegroundColor White
Write-Host ' BCA Robot - installer' -ForegroundColor White
Write-Host '=========================================' -ForegroundColor White
Write-Host ("Project folder: {0}" -f $root)

$total = 7

Write-Step 1 $total 'Checking Python...'
$python = Resolve-Python
Write-Ok $python

Write-Step 2 $total 'Preparing the virtual environment...'
$venvPython = Ensure-Venv -RepoRoot $root -PythonExe $python
Write-Ok $venvPython

Write-Step 3 $total 'Installing the robot packages...'
Invoke-Native -Exe $venvPython -Arguments @('-m', 'pip', 'install', '-r', (Join-Path $root 'requirements.txt')) -Label 'pip install'
Write-Ok 'Robot packages installed.'

Write-Step 4 $total 'Installing the Playwright browser (backoffice upload)...'
if ($SkipPlaywright) {
    Write-Warn 'Skipped (-SkipPlaywright).'
} else {
    Invoke-Native -Exe $venvPython -Arguments @('-m', 'playwright', 'install', 'chromium') -Label 'playwright install'
    Write-Ok 'Playwright chromium installed.'
}

Write-Step 5 $total 'Checking Google Chrome...'
$cfg = Get-Content -LiteralPath (Join-Path $root 'config.json') -Raw | ConvertFrom-Json
$chrome = $cfg.chrome_exe
if ($chrome -and (Test-Path -LiteralPath $chrome)) {
    Write-Ok $chrome
} else {
    Write-Warn ("Chrome not found at '{0}'." -f $chrome)
    Write-Warn 'Install Google Chrome from https://www.google.com/chrome/, or fix chrome_exe in config.json.'
}

Write-Step 6 $total 'Preparing folders...'
New-Item -ItemType Directory -Path (Join-Path $root 'output') -Force | Out-Null
if (Test-Path -LiteralPath (Join-Path $root 'assets')) {
    Write-Ok 'output/ ready; assets/ found.'
} else {
    Write-Warn 'output/ ready, but assets/ is missing (needed to find buttons).'
}

Write-Step 7 $total 'Creating the run launcher...'
Write-Launcher -Path (Join-Path $root 'run_robot.cmd') -RepoRoot $root -VenvPython $venvPython -ScriptRel 'api.py' -Title 'BCA Robot Server'
Write-Ok 'Created run_robot.cmd (double-click it to start the robot server).'

if ($cfg.robot_token -eq 'testtoken' -or -not $cfg.robot_token) {
    Write-Warn 'robot_token in config.json is weak/default. Set a strong value and use the same one in the panel.'
}

if ($Unattended) {
    Write-Host ''
    Write-Host 'Setting up unattended autostart...' -ForegroundColor Cyan
    if (-not (Test-Admin)) {
        Write-Err 'Unattended setup needs Administrator. Re-run from an Administrator PowerShell:'
        Write-Host ("      powershell -ExecutionPolicy Bypass -File ""{0}"" -Unattended" -f $PSCommandPath)
    } else {
        $deployScript = Join-Path $root 'deploy\windows-unattended.ps1'
        $deployArgs = @('-RepoDir', $root, '-PythonExe', $venvPython, '-RemoteSubnet', $RemoteSubnet)
        if ($AutoLogonUser) { $deployArgs += @('-AutoLogonUser', $AutoLogonUser) }
        & $deployScript @deployArgs
    }
}

Write-Host ''
Write-Host 'Done. Next steps:' -ForegroundColor Cyan
Write-Host '  1. Capture the reference images once:'
Write-Host ("       ""{0}"" main.py --capture" -f $venvPython)
Write-Host '  2. Start the robot by double-clicking run_robot.cmd'
Write-Host '  3. In the control panel, add this robot:'
Write-Host ("       host 127.0.0.1, port {0}, token = robot_token from config.json" -f $cfg.api_port)
