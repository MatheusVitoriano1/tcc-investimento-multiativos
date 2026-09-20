@echo off
rem Encerra a API de cotacoes.
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*uvicorn api_cotacoes*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
echo API encerrada.
