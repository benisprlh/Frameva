@echo off
setlocal
cd /d "%~dp0"
for %%V in (3.13 3.12 3.11) do (
  py -%%V -c "import sys" >nul 2>&1
  if not errorlevel 1 (
    py -%%V scripts\bootstrap.py %*
    goto finished
  )
)
python -c "import sys; sys.exit(0 if (3,11) <= sys.version_info[:2] < (3,14) else 1)" >nul 2>&1
if errorlevel 1 (
  echo Install Python 3.11, 3.12, or 3.13 from https://www.python.org/downloads/windows/
  echo Then run this launcher again.
  pause
  exit /b 1
)
python scripts\bootstrap.py %*
:finished
set "framevaResult=%ERRORLEVEL%"
if not "%framevaResult%"=="0" pause
endlocal & exit /b %framevaResult%
