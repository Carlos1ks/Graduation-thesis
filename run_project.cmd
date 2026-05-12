@echo off
setlocal
powershell -NoLogo -ExecutionPolicy Bypass -File "%~dp0run_project.ps1" %*
pause
