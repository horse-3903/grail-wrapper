@echo off
cd /d "%~dp0"
title Holy Grail Mk 6 Index
echo Starting Holy Grail Mk 6 Index server...
start "Holy Grail Mk 6 Index server" /min cmd /c python server.py
timeout /t 2 /nobreak >nul
start "" http://127.0.0.1:8765/
