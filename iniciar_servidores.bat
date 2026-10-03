@echo off
REM ============================================================
REM AI Lyrics - inicia os servers de desenvolvimento.
REM
REM   Backend : uvicorn api.app:app --reload --port 8000
REM   Frontend: Vite dev server (frontend/, porta 5173)
REM
REM Cada processo abre em janela propria (logs separados - feche
REM a janela ou Ctrl+C para parar). O pipeline NAO e iniciado:
REM use a UI ou POST http://127.0.0.1:8000/pipeline/start.
REM ============================================================
cd /d "%~dp0"

start "AI Lyrics - Backend :8000" cmd /k "uvicorn api.app:app --reload --port 8000"
start "AI Lyrics - Frontend :5173" cmd /k "cd /d %~dp0frontend && npm run dev"

echo.
echo  Servers iniciados em janelas separadas:
echo    Backend  : http://127.0.0.1:8000
echo    Frontend : http://localhost:5173
echo.
echo  O backend leva ~1min carregando o modelo Whisper na GPU.
echo.
