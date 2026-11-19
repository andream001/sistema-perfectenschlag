@echo off
title Sistema Perfectenschlag — Desligando Stack Completa
cd /d "%~dp0"

echo [1/3] Encerrando servidores Python (portas 8080 e 5000)...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*servidor_dunder_mifflin.py*' -or $_.CommandLine -like '*webhook_receiver.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"

echo [2/3] Parando n8n (porta 5678)...
docker compose -f docker-compose.n8n.yml stop

echo [3/3] Parando Evolution API (porta 8081)...
docker compose -f assistant-to-the-lead-manager\docker-compose.evolution.yml stop

echo Sistema Perfectenschlag encerrado com seguranca!
timeout /t 3 /nobreak >nul
