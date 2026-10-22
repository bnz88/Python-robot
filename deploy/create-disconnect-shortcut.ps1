#Requires -Version 5.1
<#
.SYNOPSIS
    Create the "Disconnect VM (keep running)" shortcut on the current desktop.

.DESCRIPTION
    Points a desktop shortcut at deploy\disconnect-to-console.cmd, which detaches
    the RDP session to the console so the robot keeps working after the Remote
    Desktop window is closed. The script folder is used as the target, so it works
    wherever the repository is cloned.

.EXAMPLE
    .\create-disconnect-shortcut.ps1
#>
[CmdletBinding()]
param(
    [string]$Name = 'Disconnect VM (keep running)'
)

$ErrorActionPreference = 'Stop'

$target = Join-Path $PSScriptRoot 'disconnect-to-console.cmd'
if (-not (Test-Path -LiteralPath $target)) {
    throw "Missing $target"
}

$desktop = [Environment]::GetFolderPath('Desktop')
$linkPath = Join-Path $desktop ($Name + '.lnk')

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($linkPath)
$shortcut.TargetPath = $target
$shortcut.WorkingDirectory = (Split-Path -Parent $PSScriptRoot)
$shortcut.IconLocation = "$env:SystemRoot\System32\imageres.dll,27"
$shortcut.Description = 'Detach RDP to the console and keep the robot running'
$shortcut.Save()

Write-Host "Created $linkPath"
