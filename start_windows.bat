@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>&1
if errorlevel 1 goto missing_python
if /i "%~1"=="--check" goto check
py -3 app.py
if errorlevel 1 goto failed
exit /b 0

:check
py -3 -c "import app; print('Startup imports OK')"
exit /b %errorlevel%

:missing_python
echo Python Launcher was not found.
echo Install Python 3.12 with Tcl/Tk and Python Launcher:
echo https://www.python.org/downloads/windows/
echo Or download NJ-Cooking.exe from a successful GitHub Actions build.
if /i "%~1"=="--check" exit /b 1
pause
exit /b 1

:failed
echo The application exited with an error. Copy the message above.
pause
exit /b 1
