@echo off
rem ============================================================
rem  Start Standalone Redis in WSL (Ubuntu)
rem  Binds to 127.0.0.1:6379 with in-memory persistence
rem ============================================================
chcp 65001 >nul
echo Starting Redis Server in WSL (127.0.0.1:6379)...
wsl -u root -e bash -c "exec redis-server --bind 127.0.0.1 --save '' --appendonly no"
pause
