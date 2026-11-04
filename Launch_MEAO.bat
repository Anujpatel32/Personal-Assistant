@echo off
cd /d "%~dp0"
start "" "llama_env\Scripts\pythonw.exe" companion.py %*
