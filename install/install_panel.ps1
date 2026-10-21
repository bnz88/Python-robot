<#
.SYNOPSIS
    One-click installer for the BCA Control Panel (app.py).

.DESCRIPTION
    Double-click install_panel.cmd (or run this file). It will:
      1. find Python (and offer to install it with winget if missing);
      2. create an isolated virtual environment (.venv);
      3. install the panel's Python packages;
      4. create the panel database and the admin account;
      5. create run_panel.cmd;
      6. print what to do next.

    Use -Unattended (from an Administrator window) to also register the robot
    and panel to start automatically at logon on an always-on VM.

.PARAMETER PanelAdminPassword
    Set the admin password now. If omitted, the password from
    control_panel\config.json is used (the default is '123456' - change it
    after the first login).

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
    [string]$PanelAdminPassword,
    [switch]$Unattended,
    [string]$AutoLogonUser,
    [string]$RemoteSubnet = 'LocalSubnet'
)

. (Join-Path $PSScriptRoot '_common.ps1')

$root = Get-RepoRoot -InstallerDir $PSScriptRoot

$panelConfigPath = Join-Path $root 'control_panel\config.json'
if (-not (Test-Path -LiteralPath $panelConfigPath)) {
    $panelExample = Join-Path $root 'control_panel\config.example.json'
    if (-not (Test-Path -LiteralPath $panelExample)) {
        throw 'Missing control_panel\config.json (and no config.example.json to copy).'
    }
    Copy-Item -LiteralPath $panelExample -Destination $panelConfigPath
    Write-Host '   !   control_panel\config.json created from the example - set secret_key and the admin password.' -ForegroundColor Yellow
}

Write-Host '=========================================' -ForegroundColor White
Write-Host ' BCA Control Panel - installer' -ForegroundColor White
Write-Host '=========================================' -ForegroundColor White
Write-Host ("Project folder: {0}" -f $root)

$total = 6

Write-Step 1 $total 'Checking Python...'
$python = Resolve-Python
Write-Ok $python

Write-Step 2 $total 'Preparing the virtual environment...'
$venvPython = Ensure-Venv -RepoRoot $root -PythonExe $python
Write-Ok $venvPython

Write-Step 3 $total 'Installing the panel packages...'
Invoke-Native -Exe $venvPython -Arguments @('-m', 'pip', 'install', '-r', (Join-Path $root 'control_panel\requirements.txt')) -Label 'pip install'
Write-Ok 'Panel packages installed.'

Write-Step 4 $total 'Creating the database and admin account...'
$helper = Join-Path $root 'deploy\set_panel_admin_password.py'
if ($PanelAdminPassword) {
    $env:BCA_PANEL_ADMIN_PASSWORD = $PanelAdminPassword
    try {
        Invoke-Native -Exe $venvPython -Arguments @($helper, $root) -Label 'panel bootstrap'
    } finally {
        Remove-Item Env:\BCA_PANEL_ADMIN_PASSWORD -ErrorAction SilentlyContinue
    }
    Write-Ok 'Admin account ready with your password.'
} else {
    Invoke-Native -Exe $venvPython -Arguments @($helper, $root) -Label 'panel bootstrap'
    Write-Warn 'Using the password from control_panel\config.json (default 123456). Change it after the first login.'
}

Write-Step 5 $total 'Creating the run launcher...'
Write-Launcher -Path (Join-Path $root 'run_panel.cmd') -RepoRoot $root -VenvPython $venvPython -ScriptRel 'control_panel\app.py' -Title 'BCA Control Panel'
Write-Ok 'Created run_panel.cmd (double-click it to start the panel).'

Write-Step 6 $total 'Reading the panel address...'
$panelCfg = Get-Content -LiteralPath (Join-Path $root 'control_panel\config.json') -Raw | ConvertFrom-Json
$panelPort = $panelCfg.panel_port
Write-Ok ("Panel will listen on http://127.0.0.1:{0}" -f $panelPort)
if ($panelCfg.panel_host -ne '127.0.0.1' -and -not $PanelAdminPassword) {
    Write-Warn 'panel_host is not 127.0.0.1 and the default password is in use. Change the password before exposing the panel.'
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
        if ($PanelAdminPassword) { $deployArgs += @('-PanelAdminPassword', $PanelAdminPassword) }
        if ($AutoLogonUser) { $deployArgs += @('-AutoLogonUser', $AutoLogonUser) }
        & $deployScript @deployArgs
    }
}

Write-Host ''
Write-Host 'Done. Next steps:' -ForegroundColor Cyan
Write-Host '  1. Double-click run_panel.cmd to start the panel.'
Write-Host ("  2. Open http://127.0.0.1:{0} and log in." -f $panelPort)
Write-Host '  3. Add your robot(s) on the Dashboard (Add robot).'
Write-Host '  4. Change the admin password on the Users page.'
