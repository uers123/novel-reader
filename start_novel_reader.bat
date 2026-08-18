@echo off
setlocal
cd /d "%~dp0"

rem ---------------------------------------------------------------
rem  Novel Reader launcher
rem  1. resolve Python  2. check/install deps  3. start backend
rem  4. poll until ready (max 90s)  5. open browser only when ready
rem ---------------------------------------------------------------

if "%PORT%"=="" set "PORT=5000"

if not "%NOVEL_READER_PYTHON%"=="" (
  set "PYTHON_EXE=%NOVEL_READER_PYTHON%"
) else (
  set "PYTHON_EXE=python"
)

echo Using Python: %PYTHON_EXE%

rem --- dependency check ---
"%PYTHON_EXE%" -c "import flask, flask_cors, requests, bs4, deep_translator" >nul 2>nul
if errorlevel 1 (
  echo Installing backend dependencies...
  "%PYTHON_EXE%" -m pip install -r backend\requirements.txt
  if errorlevel 1 (
    echo Dependency installation failed.
    pause
    exit /b 1
  )
)

rem --- start the backend in this console (background) ---
echo Starting Novel Reader backend on http://127.0.0.1:%PORT%
start "NovelReaderBackend" /b "%PYTHON_EXE%" backend\app.py

rem --- poll until the server answers (2s interval, max 90s) ---
echo Waiting for the server to become ready...
set "READY="
for /L %%i in (1,1,45) do (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:%PORT%/' -UseBasicParsing -TimeoutSec 2; if ($r.StatusCode -eq 200) { exit 0 } } catch { exit 1 }" >nul 2>nul
  if not errorlevel 1 set "READY=1"
  if defined READY goto :ready
  timeout /t 2 /nobreak >nul
)

echo.
echo Server did not become ready within 90 seconds. Check the output above.
pause
exit /b 1

:ready
echo Server is ready. Opening browser...
start "" "http://127.0.0.1:%PORT%"

echo.
echo ------------------------------------------------------------------
echo  Server is running. Press Ctrl+C or close this window to stop it.
echo ------------------------------------------------------------------

rem --- keep this window attached: exit when the server stops ---
:running
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:%PORT%/' -UseBasicParsing -TimeoutSec 2; exit 0 } catch { exit 1 }" >nul 2>nul
if errorlevel 1 goto :stopped
timeout /t 2 /nobreak >nul
goto :running

:stopped
echo Server stopped.
pause
