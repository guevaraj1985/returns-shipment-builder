@echo off
setlocal

cd /d "%~dp0"
set "PORT=8777"
set "APP_URL=http://127.0.0.1:%PORT%/"
set "PYTHON_EXE="

if exist "%~dp0.venv\Scripts\python.exe" set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
if "%PYTHON_EXE%"=="" if exist "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" set "PYTHON_EXE=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if not "%PYTHON_EXE%"=="" goto run_app

where py >nul 2>nul
if not errorlevel 1 (
  start "" "%APP_URL%"
  py -3 shipment_csv_app.py %PORT%
  goto done
)

where python >nul 2>nul
if not errorlevel 1 (
  start "" "%APP_URL%"
  python shipment_csv_app.py %PORT%
  goto done
)

echo Could not find Python.
echo Install Python, create a .venv, or run from Codex where the bundled Python runtime exists.
pause
goto done

:run_app
start "" "%APP_URL%"
"%PYTHON_EXE%" shipment_csv_app.py %PORT%

:done
endlocal
