@echo off
setlocal
set "ROOT=%~dp0"
python "%ROOT%run.py"
if errorlevel 1 (
  echo.
  echo Clariti setup or startup failed. Read the error above, then verify Python 3.10+ and network access for package installation.
  exit /b 1
)
endlocal
