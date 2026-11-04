@echo off
REM ==============================================================
REM  Servora Hardware Agent - Windows installer
REM  Double-click this file. It will:
REM    1. check for Python (and tell you how to get it)
REM    2. install the optional printer/scale drivers
REM    3. ask for your Servora device key
REM    4. start the agent automatically every time you log in
REM ==============================================================
setlocal
cd /d "%~dp0"
set "AGENT=%~dp0servora_agent.py"
set "TASK=Servora Hardware Agent"

echo.
echo  === Servora Hardware Agent setup ===
echo.

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (where python >nul 2>nul && set "PY=python")
if not defined PY (
  echo  Python is not installed.
  echo  1. Download it from https://www.python.org/downloads/windows/
  echo  2. IMPORTANT: tick "Add python.exe to PATH" on the first screen.
  echo  3. Run this installer again.
  start https://www.python.org/downloads/windows/
  pause
  exit /b 1
)
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)"
if errorlevel 1 (
  echo  Python 3.9 or newer is required. Please update Python and try again.
  pause
  exit /b 1
)

echo  [1/3] Installing optional drivers (USB, COM port, Windows printers)...
%PY% -m pip install --quiet --upgrade pip >nul 2>nul
%PY% -m pip install --quiet -r "%~dp0requirements-optional.txt"
if errorlevel 1 echo     Some optional drivers failed to install. Network printers will still work.

echo.
echo  [2/3] Connecting to Servora...
if exist "%~dp0config.json" (
  echo     config.json already exists - keeping it. Run "%PY% servora_agent.py setup" to change it.
) else (
  %PY% "%AGENT%" setup
  if errorlevel 1 ( pause & exit /b 1 )
)

echo.
echo  [3/3] Starting the agent automatically at log-in...
REM pythonw runs without a console window
set "PYW="
for /f "delims=" %%i in ('%PY% -c "import sys,os; p=os.path.join(os.path.dirname(sys.executable),'pythonw.exe'); print(p if os.path.exists(p) else sys.executable)"') do set "PYW=%%i"
schtasks /Create /F /SC ONLOGON /RL HIGHEST /TN "%TASK%" /TR "\"%PYW%\" \"%AGENT%\" run" >nul
if errorlevel 1 (
  echo     Could not create the start-up task. Right-click this file and choose "Run as administrator".
  pause
  exit /b 1
)
schtasks /End /TN "%TASK%" >nul 2>nul
schtasks /Run /TN "%TASK%" >nul

echo.
echo  Done! The Servora Hardware Agent is now running in the background
echo  and will start automatically whenever this PC is switched on and you log in.
echo.
echo  Log file      : %~dp0servora-agent.log
echo  Find printers : %PY% servora_agent.py discover
echo  Test a printer: %PY% servora_agent.py test --address 192.168.1.50
echo  Stop / remove : schtasks /End /TN "%TASK%"  and  schtasks /Delete /TN "%TASK%" /F
echo.
pause
