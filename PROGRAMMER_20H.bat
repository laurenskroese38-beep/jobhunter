@echo off
chcp 65001 >nul
title JobHunter - programmation quotidienne
cd /d "%~dp0"
echo Creation de la tache planifiee "JobHunter" (tous les jours a 20:00)...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\installer_tache.ps1"
type logs\installation_tache.txt
echo.
timeout /t 20
