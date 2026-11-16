@echo off
rem Lance le bot en simulation (Windows). Arret : Ctrl+C.
cd /d "%~dp0"
py -m pip install -q -r requirements.txt
py -m bot run %*
pause
