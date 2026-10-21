@echo off
setlocal
cd /d "%~dp0"
echo.
echo  =========================================
echo   BCA Control Panel installer
echo  =========================================
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_panel.ps1" %*
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
  echo  Control Panel installation finished successfully.
) else (
  echo  Control Panel installation FAILED ^(exit code %RC%^). See the messages above.
)
echo.
pause
exit /b %RC%
