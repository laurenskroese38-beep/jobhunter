@echo off
chcp 65001 >nul
title JobHunter - import annuaire SECA
cd /d "%~dp0"
echo Import de l'annuaire SECA (15-25 min, une requete toutes les quelques secondes)...
.venv\Scripts\python.exe run.py seed-seca
echo.
echo Fini : data\seca_members.csv
timeout /t 20
