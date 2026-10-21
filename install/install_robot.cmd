@echo off
setlocal
cd /d "%~dp0"
echo.
echo  =========================================
echo   BCA Robot installer
echo  =========================================
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_robot.ps1" %*
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
  echo  Robot installation finished successfully.
) else (
  echo  Robot installation FAILED ^(exit code %RC%^). See the messages above.
)
echo.
pause
exit /b %RC%
