@echo off
rem Double-click to start Zavero. The window stays open so you can see any error.
cd /d "%~dp0"
".venv\Scripts\python.exe" main.py
echo.
echo Zavero stopped. Press any key to close this window.
pause >nul
