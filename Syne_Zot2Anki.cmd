@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title Zot2Anki Sync

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\sync_vocabulary.ps1" %*
set "sync_exit=%ERRORLEVEL%"

if not "%sync_exit%"=="0" (
  echo.
  echo Zot2Anki sync failed with exit code %sync_exit%.
  echo Review the error above and the run report before retrying.
  pause
)

endlocal & exit /b %sync_exit%
