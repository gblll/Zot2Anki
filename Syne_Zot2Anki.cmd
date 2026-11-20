@echo off
setlocal
chcp 65001 >nul
title Zot2Anki Sync

echo.
echo  Zot2Anki Sync
echo  Starting sync engine...
echo.

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\sync_vocabulary.ps1" %*
set "sync_exit=%ERRORLEVEL%"

if not "%sync_exit%"=="0" (
  echo.
  echo Zot2Anki sync failed with exit code %sync_exit%.
  echo Follow the instructions above. If a report path is shown, review that report.
  pause
)

endlocal & exit /b %sync_exit%
