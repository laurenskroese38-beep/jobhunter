@echo off
chcp 65001 >nul
title JobHunter - early career corporate finance Suisse
cd /d "%~dp0"

REM --- Trouver Python ---------------------------------------------------
set PY=
where py >nul 2>&1 && set PY=py -3
if not defined PY where python >nul 2>&1 && set PY=python
if not defined PY (
  echo Python n'est pas installe.
  echo Installe-le depuis https://www.python.org/downloads/ en cochant
  echo "Add python.exe to PATH", puis relance LANCER.bat.
  pause
  exit /b 1
)

REM --- Installation / mise a jour des dependances -----------------------
if not exist .venv\Scripts\python.exe (
  echo Premiere installation, 1 a 3 minutes...
  %PY% -m venv .venv || goto :erreur
  .venv\Scripts\python.exe -m pip install --upgrade pip -q
)
.venv\Scripts\python.exe -m pip install -r requirements.txt -q --disable-pip-version-check || goto :erreur
if not exist .venv\.chromium-ok (
  echo Installation du navigateur pour les sites carrieres - une seule fois, ~150 Mo...
  .venv\Scripts\python.exe -m playwright install chromium || goto :erreur
  echo ok> .venv\.chromium-ok
)
echo Verification...
.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider || goto :erreur

REM --- Passage -------------------------------------------------------------
echo.
echo Recherche en cours. C'est volontairement lent (pauses anti-blocage) :
echo environ 1 h a 1 h 30 au premier passage (plusieurs centaines de sites),
echo puis moins chaque jour (la methode d'acces a chaque site est memorisee).
echo Tu peux laisser cette fenetre ouverte et faire autre chose.
echo.
.venv\Scripts\python.exe run.py %* || goto :erreur

if exist output\offres_corporate_finance_suisse.xlsx start "" "output\offres_corporate_finance_suisse.xlsx"
echo.
echo Termine. Le rapport s'est ouvert ; il est aussi dans le dossier output.
pause
exit /b 0

:erreur
echo.
echo Une erreur est survenue. Le detail est dans le dossier logs.
pause
exit /b 1
