@echo off
cd /d "%~dp0"
start "" /wait "GorodPomnit.exe" --diagnose-graphics
if exist graphics-diagnostic.txt (
  echo Diagnostic saved: graphics-diagnostic.txt
) else (
  echo Diagnostic failed. Send this message and your Windows version.
)
pause
