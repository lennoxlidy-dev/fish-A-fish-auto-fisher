@echo off
cd /d "%~dp0"
set PY=python
where py >nul 2>nul && set PY=py
echo Installing / updating requirements...
%PY% -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 (
  echo.
  echo Could not install the requirements. Is Python installed with "Add python.exe to PATH" ticked?
  pause
  exit /b 1
)
%PY% fisher.py setup
pause
