@echo off
rem focus.bat — Launch Tempo from any terminal without blocking it.
rem The GUI runs in the background; this batch file returns immediately.
start "" pythonw.exe "%~dp0main.py" --gui %*
