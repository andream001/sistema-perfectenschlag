@echo off
title Sistema Perfectenschlag — Ligando Stack Completa
cd /d "%~dp0"

echo [1/4] Subindo Evolution API (porta 8081)...
docker compose -f assistant-to-the-lead-manager\docker-compose.evolution.yml up -d

echo [2/4] Subindo n8n Automacao (porta 5678)...
docker compose -f docker-compose.n8n.yml up -d

echo [3/4] Iniciando Assistant to the Lead Manager (porta 5000)...
start "Lead Manager (5000)" /min cmd /c "python assistant-to-the-lead-manager\webhook_receiver.py"

timeout /t 3 /nobreak >nul

echo [4/4] Iniciando Servidor Perfectenschlag AgentCraft (porta 8080)...
start "Perfectenschlag (8080)" /min cmd /c "python servidor_dunder_mifflin.py"

timeout /t 2 /nobreak >nul
start "" "http://localhost:8080"
start "" "http://localhost:5000"
start "" "http://localhost:5678"
echo Tudo iniciado! Pressione qualquer tecla para fechar esta janela.
pause >nul
