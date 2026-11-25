@echo off
cd /d "%~dp0"
set PYTHONPATH=%~dp0src
python -m g2s ui --work-dir D:\G2S
pause
