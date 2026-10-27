@echo off
rem Double-click to start Zavero. No console window: quit from the Zavero icon in the tray.
rem Problems are written to logs\zavero.log. To see output live, run: .venv\Scripts\python.exe main.py
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" main.py
