@echo off
rem Inicia a API de cotacoes (se ainda nao estiver no ar) e abre o site.
cd /d "%~dp0"
powershell -NoProfile -Command "try { Invoke-WebRequest http://127.0.0.1:8000/saude -UseBasicParsing -TimeoutSec 2 | Out-Null; exit 0 } catch { exit 1 }"
if errorlevel 1 (
  echo Iniciando a API de cotacoes...
  start "API de cotacoes" /min "%~dp0venv\Scripts\python.exe" -m uvicorn api_cotacoes:app --port 8000
  timeout /t 4 /nobreak >nul
)
start "" http://localhost:8000/
