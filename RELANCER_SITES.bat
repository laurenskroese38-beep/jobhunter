@echo off
chcp 65001 >nul
title JobHunter - relance des sites (attend la fin du passage en cours)
cd /d "%~dp0"
echo En attente de la fin du passage en cours...
:attente
if not exist data\.lock goto lance
set LPID=
set /p LPID=<data\.lock
if "%LPID%"=="" goto lance
tasklist /FI "PID eq %LPID%" 2>nul | find "%LPID%" >nul || goto lance
timeout /t 30 /nobreak >nul
goto attente
:lance
echo Relance des sites carrieres - sans LinkedIn...
.venv\Scripts\python.exe run.py --no-jobspy
echo Termine. Rapport : output\offres_corporate_finance_suisse.xlsx
timeout /t 60
