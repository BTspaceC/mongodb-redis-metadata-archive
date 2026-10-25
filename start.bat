@echo off
rem ============================================================
rem  Metadata Archive & Analytics Engine - One-Click Launcher
rem  Workflow: Verify MongoDB -> Start Redis -> Sync Ranks -> Launch Server
rem ============================================================
chcp 65001 >nul
cd /d "%~dp0"

set PY=python
if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe

echo.
echo ============================================================
echo   Metadata Archive & Rarity Analytics Engine
echo ============================================================
echo.

echo [1/4] Checking MongoDB Connection...
%PY% scripts\check_services.py mongo
if errorlevel 1 goto no_mongo
echo       MongoDB is online and ready.

echo [2/4] Checking Redis Service...
%PY% scripts\check_services.py redis
if not errorlevel 1 goto redis_ready
echo       Redis is not active. Attempting to start in background (WSL)...
start "" /b wsl -u root -e bash -c "exec redis-server --bind 127.0.0.1 --save '' --appendonly no" >nul 2>&1
%PY% scripts\check_services.py wait-redis
if errorlevel 1 goto no_redis
:redis_ready
echo       Redis is online and ready.

echo [3/4] Synchronizing Redis Leaderboards...
%PY% scripts\rebuild_redis.py
if errorlevel 1 goto no_data

echo [4/4] Starting Server at http://localhost:8000 ...
echo       Press Ctrl+C to stop the server at any time.
echo.
if not defined NO_BROWSER start "" /b cmd /c "timeout /t 3 >nul & start http://localhost:8000"
%PY% -m uvicorn app.main:app --port 8000
goto end

:no_mongo
echo.
echo [Error] Failed to connect to MongoDB.
echo         Please ensure MongoDB service is running (e.g., via Docker: docker compose up -d)
goto end

:no_redis
echo.
echo [Error] Timed out waiting for Redis service.
echo         Please ensure Redis is started or run: docker compose up -d
goto end

:no_data
echo.
echo [Warn] Leaderboard sync skipped: collections have not been imported yet.
echo        Please run:
echo          python scripts\import_data.py
echo          python scripts\compute_rarity.py
goto end

:end
echo.
pause
