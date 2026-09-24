@echo off
cd /d "%~dp0"
set /p PORT=Enter Arduino port (example COM5): 
python -m src.app --port %PORT%
pause
