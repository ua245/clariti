@echo off
setlocal
set "ROOT=%~dp0"
set "VENV=%ROOT%.venv"
set "PYTHON=%VENV%\Scripts\python.exe"

if not exist "%PYTHON%" (
  echo Creating project-local virtual environment...
  python -m venv "%VENV%"
  if errorlevel 1 goto :error
)

if not exist "%VENV%\requirements.txt" goto :install
fc /b "%ROOT%requirements.txt" "%VENV%\requirements.txt" >nul
if errorlevel 1 goto :install
goto :start

:install
echo Installing pinned requirements...
"%PYTHON%" -m pip install --disable-pip-version-check -r "%ROOT%requirements.txt"
if errorlevel 1 goto :error
copy /y "%ROOT%requirements.txt" "%VENV%\requirements.txt" >nul

:start
echo Starting Clariti at http://127.0.0.1:8765
"%PYTHON%" -m app.launch
goto :end

:error
echo.
echo Clariti setup or startup failed. Read the error above, then verify Python and network access for package installation.
exit /b 1

:end
endlocal
