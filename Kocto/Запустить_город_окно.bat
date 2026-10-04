cd /d "%~dp0"
chcp 65001 >nul
python -m gorod.ui_tk
if errorlevel 1 pause
