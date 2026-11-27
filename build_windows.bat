@echo off
cd /d "%~dp0"
python -m pip install . "pyinstaller>=6.11" || exit /b 1
python build.py
exit /b %ERRORLEVEL%
