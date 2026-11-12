@echo off
REM Passage quotidien lance par le Planificateur de taches Windows (tache "JobHunter", 20:00).
cd /d "%~dp0"
if not exist logs mkdir logs
echo ===== %date% %time% ===== >> logs\tache_quotidienne.log
.venv\Scripts\python.exe run.py >> logs\tache_quotidienne.log 2>&1
echo Fin : code %errorlevel% >> logs\tache_quotidienne.log
