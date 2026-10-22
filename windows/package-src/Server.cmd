@echo off
if not "%~1"=="" goto cli
start "" "%~dp0Server.exe"
exit /b
:cli
call "%~dp0Server-CLI.cmd" %*
exit /b %errorlevel%
