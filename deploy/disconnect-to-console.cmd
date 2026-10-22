@echo off
rem Double-click target for the desktop shortcut: detach the RDP session to the
rem console so the robot keeps running after this window closes.
rem Usage: disconnect-to-console.cmd [-DisableSleep] [-DryRun]
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0disconnect-to-console.ps1" %*
