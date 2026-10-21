<#
.SYNOPSIS
    Prepare a cloud Windows VM to run the BCA control panel and/or robot
    unattended, surviving RDP disconnect and reboot.

.DESCRIPTION
    Run this once on each Windows VM, from an elevated PowerShell, after copying
    the repo. It performs the VM-level setup that the plan requires:
      * never-lock registry policy (no lock screen, no machine inactivity lock,
        no screen saver) so GUI automation keeps working while disconnected;
      * RDS/RDP session policy so a disconnected session is never ended;
      * Windows Firewall rules for the panel and robot ports, scoped to the
        private network only;
      * optional auto-login so the VM boots into an interactive session;
      * two Scheduled Tasks that start the panel and the robot server at logon
        ("run only when user is logged on", i.e. inside the interactive session),
        with restart-on-failure and size-rotated logs.

    The scraper (main.py) is intentionally NOT started here: it is launched by
    the panel when the operator presses Start.

.PARAMETER RepoDir
    Repository root. Defaults to the parent of the folder containing this script.

.PARAMETER PythonExe
    Full path to the real Python interpreter (not the Microsoft Store alias).
    Auto-detected via the 'py' launcher or Get-Command when omitted.

.PARAMETER PanelPort
    Panel HTTP port. Default 5000.

.PARAMETER RobotPort
    Robot API HTTP port. Default 8000.

.PARAMETER RemoteSubnet
    Firewall remote scope for the robot and RDP rules. Default 'LocalSubnet'.

.PARAMETER PanelAllow
    Remote scope for the panel port only (an IP or CIDR such as 10.0.1.7 or
    10.0.1.0/24). Defaults to -RemoteSubnet. Tighten this to the operator VM.

.PARAMETER AutoLogonUser
    User account to auto-login at boot. If given without -AutoLogonPassword the
    password is prompted for securely (not read from the command line).

.PARAMETER AutoLogonPassword
    Password for -AutoLogonUser. Prefer omitting this and letting the script
    prompt, so the value is not visible in the process list or shell history.

.PARAMETER PanelAdminPassword
    Set the control panel admin password now (updates panel.db and
    control_panel/config.json). Required when the configured password is still
    the weak default, unless -AllowWeakAdminPassword is passed.

.PARAMETER AllowWeakAdminPassword
    Proceed even when the panel admin password is the weak/default value.

.PARAMETER ScopeRdpToLocalSubnet
    Restrict the built-in Remote Desktop rules to -RemoteSubnet. Requires an
    explicit CIDR (not 'LocalSubnet'); can lock you out of RDP if you connect
    from outside the range.

.PARAMETER Remove
    Undo: unregister the tasks, remove the firewall rules, and clear auto-login
    (including the stored password). Never-lock and RDS policy values are left
    in place (they are harmless).

.EXAMPLE
    # Panel + robot on one VM, prompt for the auto-login password
    .\windows-unattended.ps1 -AutoLogonUser operator -PanelAdminPassword 'str0ng-Pass!'

.EXAMPLE
    # Robot-only VM, panel port scoped to the operator VM
    .\windows-unattended.ps1 -PanelAllow 10.0.1.7
#>
[CmdletBinding()]
param(
    [string]    $RepoDir,
    [string]    $PythonExe,
    [int]       $PanelPort = 5000,
    [int]       $RobotPort = 8000,
    [string]    $RemoteSubnet = 'LocalSubnet',
    [string[]]  $PanelAllow,
    [string]    $AutoLogonUser,
    [string]    $AutoLogonPassword,
    [string]    $PanelAdminPassword,
    [switch]    $AllowWeakAdminPassword,
    [switch]    $ScopeRdpToLocalSubnet,
    [switch]    $Remove
)

$ErrorActionPreference = 'Stop'

$PanelTask = 'BCA-ControlPanel'
$RobotTask = 'BCA-Robot'
$PanelRule = 'BCA Control Panel'
$RobotRule = 'BCA Robot API'
$Winlogon = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon'
$MaxLogBytes = 10485760

function Assert-Admin {
    $principal = New-Object Security.Principal.WindowsPrincipal(
        [Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'This script must be run from an elevated (Administrator) PowerShell.'
    }
}

function Resolve-RepoDir {
    if ($RepoDir) {
        $resolved = (Resolve-Path -LiteralPath $RepoDir).Path
    } else {
        $resolved = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
    }
    foreach ($needed in @('api.py', 'control_panel\app.py')) {
        if (-not (Test-Path -LiteralPath (Join-Path $resolved $needed))) {
            throw "RepoDir '$resolved' does not look like the repo (missing $needed)."
        }
    }
    return $resolved
}

function Resolve-Python {
    if ($PythonExe) {
        if (-not (Test-Path -LiteralPath $PythonExe)) {
            throw "PythonExe '$PythonExe' not found."
        }
        if ($PythonExe -match 'WindowsApps') {
            throw "PythonExe '$PythonExe' is the Microsoft Store alias; use the real interpreter path."
        }
        return (Resolve-Path -LiteralPath $PythonExe).Path
    }

    $candidates = @()
    try {
        $candidates += & py -3 -c "import sys; print(sys.executable)" 2>$null
    } catch { }
    $cmd = Get-Command python.exe -All -ErrorAction SilentlyContinue |
        Where-Object { $_.Source -notmatch 'WindowsApps' }
    if ($cmd) { $candidates += $cmd[0].Source }

    foreach ($c in $candidates) {
        if ($c -and (Test-Path -LiteralPath $c) -and $c -notmatch 'WindowsApps') {
            return (Resolve-Path -LiteralPath $c).Path
        }
    }
    throw "Could not auto-detect a real Python interpreter. Pass -PythonExe '<full path>'."
}

function Read-PlainPassword {
    param([string]$Prompt)
    $secure = Read-Host -Prompt $Prompt -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
}

function Set-RegValue {
    param([string]$Path, [string]$Name, $Value, [string]$Type = 'DWord')
    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -Path $Path -Force | Out-Null
    }
    New-ItemProperty -LiteralPath $Path -Name $Name -Value $Value -PropertyType $Type -Force | Out-Null
}

function Get-PanelAdminPassword {
    param([string]$Dir)
    $p = Join-Path $Dir 'control_panel\config.json'
    if (-not (Test-Path -LiteralPath $p)) { return $null }
    return (Get-Content -LiteralPath $p -Raw | ConvertFrom-Json).admin_password
}

function Remove-FirewallRuleIfPresent {
    param([string]$DisplayName)
    Get-NetFirewallRule -DisplayName $DisplayName -ErrorAction SilentlyContinue |
        Remove-NetFirewallRule -ErrorAction SilentlyContinue
}

function Write-Launcher {
    param([string]$Path, [string]$Repo, [string]$Python, [string]$ScriptRel, [string]$OutDir, [string]$LogPath)
    $lines = @(
        '@echo off'
        ('if not exist "{0}" mkdir "{0}"' -f $OutDir)
        ('cd /d "{0}"' -f $Repo)
        ('if exist "{0}" for %%F in ("{0}") do if %%~zF GEQ {1} move /y "{0}" "{0}.1"' -f $LogPath, $MaxLogBytes)
        ('"{0}" "{1}" >> "{2}" 2>&1' -f $Python, $ScriptRel, $LogPath)
    )
    Set-Content -LiteralPath $Path -Value $lines -Encoding ASCII
}

function Uninstall {
    foreach ($task in @($PanelTask, $RobotTask)) {
        Unregister-ScheduledTask -TaskName $task -Confirm:$false -ErrorAction SilentlyContinue
    }
    foreach ($rule in @($PanelRule, $RobotRule)) {
        Remove-FirewallRuleIfPresent -DisplayName $rule
    }
    Set-RegValue $Winlogon 'AutoAdminLogon' '0' 'String'
    Remove-ItemProperty -LiteralPath $Winlogon -Name 'DefaultPassword', 'DefaultUserName', 'DefaultDomainName' -ErrorAction SilentlyContinue
    Write-Host 'Removed tasks, firewall rules, and auto-login (including the stored password).' -ForegroundColor Yellow
}

function Get-ConfigWarnings {
    param([string]$Dir)
    $panelCfg = Join-Path $Dir 'control_panel\config.json'
    $robotCfg = Join-Path $Dir 'config.json'
    if (Test-Path -LiteralPath $panelCfg) {
        $c = Get-Content -LiteralPath $panelCfg -Raw | ConvertFrom-Json
        if ($c.panel_host -eq '127.0.0.1') {
            Write-Warning "control_panel\config.json panel_host is 127.0.0.1; remote operator VMs cannot reach it. Set it to 0.0.0.0 for private-network access."
        }
    }
    if (Test-Path -LiteralPath $robotCfg) {
        $c = Get-Content -LiteralPath $robotCfg -Raw | ConvertFrom-Json
        if ($c.robot_token -eq 'testtoken' -or -not $c.robot_token) {
            Write-Warning "config.json robot_token is weak/default. Generate a strong token and match it in the panel's robot entry."
        }
    }
}

Assert-Admin

if ($Remove) {
    Uninstall
    return
}

$repo = Resolve-RepoDir
$python = Resolve-Python
"Repo:   $repo"
"Python: $python"

$genDir = Join-Path $repo 'deploy\generated'
New-Item -ItemType Directory -Path $genDir -Force | Out-Null
$outputDir = Join-Path $repo 'output'
New-Item -ItemType Directory -Path $outputDir -Force | Out-Null

Write-Host 'Checking the panel admin password...' -ForegroundColor Green
if ($PanelAdminPassword) {
    $env:BCA_PANEL_ADMIN_PASSWORD = $PanelAdminPassword
    try {
        & $python (Join-Path $PSScriptRoot 'set_panel_admin_password.py') $repo
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to set the panel admin password (exit $LASTEXITCODE)."
        }
    } finally {
        Remove-Item Env:\BCA_PANEL_ADMIN_PASSWORD -ErrorAction SilentlyContinue
    }
}
$currentAdminPw = Get-PanelAdminPassword -Dir $repo
if ((-not $currentAdminPw) -or ($currentAdminPw -eq '123456')) {
    if ($AllowWeakAdminPassword) {
        Write-Warning 'Panel admin password is weak/default and -AllowWeakAdminPassword was set; continuing.'
    } else {
        throw "Panel admin password is weak/default. Pass -PanelAdminPassword '<new>' to set one now (or change it in the panel Users page), then re-run. Add -AllowWeakAdminPassword to override."
    }
}

Write-Host 'Configuring never-lock policies...' -ForegroundColor Green
# No lock screen / no machine inactivity lock.
Set-RegValue 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\Personalization' 'NoLockScreen' 1
Set-RegValue 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System' 'InactivityTimeoutSecs' 0
# Screen saver disabled by policy (applies to all users).
Set-RegValue 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\Control Panel\Desktop' 'ScreenSaveActive' '0' 'String'
Set-RegValue 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\Control Panel\Desktop' 'ScreenSaverIsSecure' '0' 'String'
Set-RegValue 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\Control Panel\Desktop' 'ScreenSaveTimeOut' '0' 'String'

Write-Host 'Configuring RDP/RDS session limits (never end disconnected sessions)...' -ForegroundColor Green
$ts = 'HKLM:\SOFTWARE\Policies\Microsoft\Windows NT\Terminal Services'
Set-RegValue $ts 'MaxDisconnectionTime' 0
Set-RegValue $ts 'MaxIdleTime' 0
Set-RegValue $ts 'MaxConnectionTime' 0

Write-Host 'Creating firewall rules (private network only)...' -ForegroundColor Green
$panelScope = if ($PanelAllow) { $PanelAllow } else { $RemoteSubnet }
Remove-FirewallRuleIfPresent -DisplayName $PanelRule
Remove-FirewallRuleIfPresent -DisplayName $RobotRule
New-NetFirewallRule -DisplayName $PanelRule -Direction Inbound -Action Allow `
    -Protocol TCP -LocalPort $PanelPort -RemoteAddress $panelScope -Profile Any | Out-Null
New-NetFirewallRule -DisplayName $RobotRule -Direction Inbound -Action Allow `
    -Protocol TCP -LocalPort $RobotPort -RemoteAddress $RemoteSubnet -Profile Any | Out-Null
if ($ScopeRdpToLocalSubnet) {
    if ($RemoteSubnet -eq 'LocalSubnet') {
        throw "ScopeRdpToLocalSubnet needs an explicit -RemoteSubnet CIDR (e.g. 10.0.1.0/24); refusing to scope RDP to the ambiguous 'LocalSubnet'."
    }
    Write-Warning "Restricting the built-in Remote Desktop rules to $RemoteSubnet. If you connect from outside that range you will be locked out of RDP; keep the cloud console as a recovery path."
    Get-NetFirewallRule -DisplayGroup 'Remote Desktop' -ErrorAction SilentlyContinue |
        Set-NetFirewallRule -RemoteAddress $RemoteSubnet
}

if ($AutoLogonUser -and -not $AutoLogonPassword) {
    try {
        $AutoLogonPassword = Read-PlainPassword -Prompt "Auto-login password for $AutoLogonUser"
    } catch {
        Write-Warning 'Could not read the auto-login password interactively; auto-login will not be configured.'
    }
}

$user = if ($AutoLogonUser) {
    if ($AutoLogonUser -match '\\') { $AutoLogonUser } else { "$env:COMPUTERNAME\$AutoLogonUser" }
} else { "$env:COMPUTERNAME\$env:USERNAME" }

if ($AutoLogonUser -and $AutoLogonPassword) {
    Write-Host "Configuring auto-login for $AutoLogonUser..." -ForegroundColor Green
    Set-RegValue $Winlogon 'AutoAdminLogon' '1' 'String'
    Set-RegValue $Winlogon 'DefaultUserName' $AutoLogonUser 'String'
    Set-RegValue $Winlogon 'DefaultPassword' $AutoLogonPassword 'String'
    $domain = if ($AutoLogonUser -match '\\') { $AutoLogonUser.Split('\')[0] } else { $env:COMPUTERNAME }
    Set-RegValue $Winlogon 'DefaultDomainName' $domain 'String'
    Write-Warning 'Auto-login stores the password in plain text in the registry; use Sysinternals Autologon for encrypted storage if you need that.'
} elseif ($AutoLogonUser) {
    Write-Warning 'AutoLogonUser given without a password; auto-login not configured.'
} else {
    Write-Host 'Auto-login not configured; set it manually (or pass -AutoLogonUser so the VM boots into an interactive session).' -ForegroundColor Yellow
}

Write-Host 'Writing launcher scripts...' -ForegroundColor Green
$panelLog = Join-Path $outputDir 'panel.log'
$robotLog = Join-Path $outputDir 'robot.log'
Write-Launcher -Path (Join-Path $genDir 'start_panel.cmd') -Repo $repo -Python $python `
    -ScriptRel 'control_panel\app.py' -OutDir $outputDir -LogPath $panelLog
Write-Launcher -Path (Join-Path $genDir 'start_robot.cmd') -Repo $repo -Python $python `
    -ScriptRel 'api.py' -OutDir $outputDir -LogPath $robotLog

Write-Host 'Registering scheduled tasks (at logon, interactive session)...' -ForegroundColor Green
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Highest
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user

foreach ($spec in @(
        @{ Name = $PanelTask; Launcher = (Join-Path $genDir 'start_panel.cmd') },
        @{ Name = $RobotTask; Launcher = (Join-Path $genDir 'start_robot.cmd') })) {
    $action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument ('/c "{0}"' -f $spec.Launcher)
    Register-ScheduledTask -TaskName $spec.Name -Action $action -Trigger $trigger `
        -Principal $principal -Settings $settings -Force | Out-Null
    Write-Host ("  registered {0} -> {1}" -f $spec.Name, $spec.Launcher)
}

Write-Host 'Writing an RDP template with a fixed resolution...' -ForegroundColor Green
@"
screen mode id:i:2
use multimon:i:0
desktopwidth:i:1920
desktopheight:i:1080
session bpp:i:32
smart sizing:i:0
full address:s:CHANGE-ME-PRIVATE-IP
"@ | Set-Content -LiteralPath (Join-Path $genDir 'desktop.rdp') -Encoding ASCII

Get-ConfigWarnings -Dir $repo

Write-Host ''
Write-Host 'Done. Next steps:' -ForegroundColor Cyan
Write-Host ("  1. Confirm auto-login works: reboot and check {0} comes up logged in." -f $env:COMPUTERNAME)
Write-Host ("  2. Open the panel from the operator VM (private IP, port {0})." -f $PanelPort)
Write-Host '  3. Press Start, then DISCONNECT RDP (do not Sign out); verify a scrape completes.'
Write-Host ("  Logs: {0} , {1}" -f $panelLog, $robotLog)
Write-Host '  To undo: .\windows-unattended.ps1 -Remove'
