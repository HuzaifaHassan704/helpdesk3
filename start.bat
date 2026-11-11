@echo off
rem Double-click to start the app, or run:  start.bat
cd /d "%~dp0"
where python >nul 2>&1
if %errorlevel%==0 (python start.py %*) else (py -3 start.py %*)
if errorlevel 1 pause
