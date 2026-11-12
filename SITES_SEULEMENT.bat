@echo off
chcp 65001 >nul
title JobHunter - sites carrieres seulement
cd /d "%~dp0"
echo Passage sur les sites carrieres uniquement - sans LinkedIn / Indeed...
.venv\Scripts\python.exe run.py --no-jobspy
if exist output\offres_corporate_finance_suisse.xlsx start "" "output\offres_corporate_finance_suisse.xlsx"
timeout /t 30
