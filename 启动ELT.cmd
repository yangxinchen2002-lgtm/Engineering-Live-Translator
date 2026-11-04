@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto missing_python
if not exist ".venv\Scripts\pythonw.exe" goto missing_python
".venv\Scripts\python.exe" -c "import PySide6; import app.ui.main" >nul 2>&1
if errorlevel 1 goto import_failed
start "" "%~dp0.venv\Scripts\pythonw.exe" -m app.ui.main
if errorlevel 1 goto launch_failed
exit /b 0

:missing_python
echo ELT could not find its Python environment. See README.md for setup.
pause
exit /b 1

:import_failed
echo ELT could not load its desktop components. Details:
".venv\Scripts\python.exe" -c "import PySide6; import app.ui.main"
pause
exit /b 1

:launch_failed
echo ELT could not start the desktop application.
pause
exit /b 1
