@echo off
cd /d "%~dp0"
title Grail Local Index
echo Starting Grail Local Index server...
start "Grail Local Index server" /min cmd /c python server.py
timeout /t 2 /nobreak >nul
start "" http://127.0.0.1:8765/
