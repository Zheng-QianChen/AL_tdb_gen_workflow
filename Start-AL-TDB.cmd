@echo off
setlocal EnableExtensions
set PYTHONUTF8=1
cd /d "%~dp0"

rem Prefer an explicitly configured interpreter so validation can reuse a known
rem Python 3.11/3.12 without downloading or touching the system site-packages.
set "LAUNCHER=%~dp0altdb\launcher.py"
if not exist "%LAUNCHER%" (
  echo ERROR: Missing "%LAUNCHER%"
  echo Extract the full ZIP or run this file from the repository root.
  pause
  exit /b 1
)

if defined AL_TDB_PYTHON (
  if not exist "%AL_TDB_PYTHON%" (
    echo ERROR: AL_TDB_PYTHON is set but not found: "%AL_TDB_PYTHON%"
    echo Point it at python.exe for Python 3.11 or 3.12.
    pause
    exit /b 1
  )
  "%AL_TDB_PYTHON%" "%LAUNCHER%" %*
  goto :capture
)

where py >nul 2>&1
if errorlevel 1 goto :try_python

py -3.12 -c "import sys" >nul 2>&1
if not errorlevel 1 (
  py -3.12 "%LAUNCHER%" %*
  goto :capture
)

py -3.11 -c "import sys" >nul 2>&1
if not errorlevel 1 (
  py -3.11 "%LAUNCHER%" %*
  goto :capture
)

py -3 -c "import sys" >nul 2>&1
if not errorlevel 1 (
  py -3 "%LAUNCHER%" %*
  goto :capture
)

:try_python
where python >nul 2>&1
if errorlevel 1 goto :no_python
python "%LAUNCHER%" %*
set "EXITCODE=%ERRORLEVEL%"
goto :finish

:no_python
echo ERROR: No supported Python found on PATH.
echo Install Python 3.11 or 3.12, or set AL_TDB_PYTHON to that python.exe.
echo This starter never downloads Python and never installs into the system environment.
pause
exit /b 1

:capture
set "EXITCODE=%ERRORLEVEL%"
:finish
if not "%EXITCODE%"=="0" (
  echo.
  echo Launcher exited with code %EXITCODE%.
  pause
)
exit /b %EXITCODE%
