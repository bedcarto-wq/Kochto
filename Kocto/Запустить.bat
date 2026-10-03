@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 campaign_launcher.py %*
) else (
  python campaign_launcher.py %*
)
if errorlevel 1 (
  echo.
  echo Не запустилось. Нужен Python 3.11+ с python.org ^(галочка "Add to PATH"^).
  pause
)
