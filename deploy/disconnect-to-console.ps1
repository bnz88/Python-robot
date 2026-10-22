#Requires -Version 5.1
<#
.SYNOPSIS
    Disconnect the current Remote Desktop session and keep it running on the
    console, so the robot keeps working after the RDP window is closed.

.DESCRIPTION
    Closing the RDP client leaves a disconnected session: the processes keep
    running, but the desktop is no longer rendered, which breaks the scraper's
    screen capture and CAPTCHA OCR. This re-attaches the session to the console
    with tscon and then drops the Remote Desktop connection.

    Run it from a desktop shortcut on the robot VM. tscon needs administrator
    rights, so the script relaunches itself elevated (one UAC prompt).

.PARAMETER DisableSleep
    Also disable standby, the monitor timeout and the screen saver, so the
    console session stays unlocked while nobody is connected.

.PARAMETER DryRun
    Print what would happen and exit without elevating or disconnecting.

.EXAMPLE
    .\disconnect-to-console.ps1

.EXAMPLE
    .\disconnect-to-console.ps1 -DisableSleep
#>
[CmdletBinding()]
param(
    [switch]$DisableSleep,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$logPath = Join-Path $env:TEMP 'bca-disconnect.log'

function Write-Log {
    param([string]$Message)
    $line = '[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
    try {
        Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8
    } catch {
    }
    Write-Host $Message
}

function Test-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole(
        [Security.Principal.WindowsBuiltinRole]::Administrator
    )
}

function Get-SessionFields {
    param([int]$SessionId)
    $rows = & query session 2>$null
    foreach ($row in $rows) {
        $fields = @($row -split '\s+' | Where-Object { $_ })
        if ($fields -contains [string]$SessionId) {
            return $fields
        }
    }
    return @()
}

if (-not $DryRun -and -not (Test-Administrator)) {
    Write-Host 'Administrator rights are required by tscon - relaunching...'
    $arguments = @(
        '-NoProfile',
        '-ExecutionPolicy',
        'Bypass',
        '-File',
        ('"{0}"' -f $PSCommandPath)
    )
    if ($DisableSleep) {
        $arguments += '-DisableSleep'
    }
    Start-Process -FilePath (Get-Process -Id $PID).Path `
        -ArgumentList $arguments -Verb RunAs
    exit 0
}

$sessionId = [System.Diagnostics.Process]::GetCurrentProcess().SessionId
$fields = @(Get-SessionFields -SessionId $sessionId)
$sessionName = ''
if ($fields.Count -gt 0) {
    # query session marks the current row with a leading ">" or "*".
    $sessionName = $fields[0].TrimStart('>', '*')
}

Write-Log ('current session: id={0} name={1}' -f $sessionId, $sessionName)

if ($sessionName -eq 'console') {
    Write-Log 'already attached to the console - nothing to detach.'
    return
}

if ($sessionName -and $sessionName -notmatch '^rdp-') {
    Write-Log ('session name "{0}" is not an RDP session; continuing anyway.' -f $sessionName)
}

if ($DisableSleep) {
    Write-Log 'disabling standby, monitor timeout and screen saver'
    if (-not $DryRun) {
        & powercfg /change standby-timeout-ac 0 | Out-Null
        & powercfg /change monitor-timeout-ac 0 | Out-Null
        Set-ItemProperty -Path 'HKCU:\Control Panel\Desktop' `
            -Name ScreenSaveActive -Value '0' -ErrorAction SilentlyContinue
    }
}

if ($DryRun) {
    Write-Log ('dry run: would execute "tscon {0} /dest:console"' -f $sessionId)
    return
}

Write-Log ('detaching session {0} to the console' -f $sessionId)
& tscon.exe $sessionId /dest:console
$exitCode = $LASTEXITCODE

if ($exitCode -ne 0) {
    Write-Log ('tscon failed with exit code {0}' -f $exitCode)
    Read-Host 'Press Enter to close'
    exit $exitCode
}

Write-Log 'session detached - the Remote Desktop window will close now'
