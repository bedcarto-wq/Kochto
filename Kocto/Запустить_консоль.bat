@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 main.py --console
) else (
  python main.py --console
)
if errorlevel 1 (
  echo.
  echo Не запустилось. Нужен Python 3.11+ с python.org ^(галочка "Add to PATH"^).
  pause
)
