@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONHOME="
set "PYTHONPATH="
set "PATH=%~dp0runtime\bin;%PATH%"
"%~dp0runtime\bin\python.exe" -B "%~dp0server.py" %*
if errorlevel 1 pause
