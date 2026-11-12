@echo off
chcp 65001 >nul
title JobHunter - diagnostic
cd /d "%~dp0"
echo 1/2 Diagnostic de la tache planifiee...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\diag_tache.ps1"
echo 2/2 Capture des sites carrieres sans resultat (10-15 min)...
.venv\Scripts\python.exe tools\dump_sites.py
echo Fini.
timeout /t 30
