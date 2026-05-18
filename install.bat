@echo off
:: Optima -- Windows installer
::
:: Run from the project root once after unzipping:
::     install.bat
::
:: What it does:
::   1. Confirms Python 3.11+ is available
::   2. Creates a virtual environment in .venv\
::   3. Installs Flask, pywebview, python-docx into the venv
::   4. Writes Optima.bat on your desktop so you can launch with a double-click

setlocal enabledelayedexpansion

cd /d "%~dp0"
set "PROJECT_DIR=%cd%"
echo ==^> Optima installer
echo     Project directory: %PROJECT_DIR%

:: ---- 1. Python check -----------------------------------------------------
where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: python is not on your PATH.
    echo        Install Python 3.11 or newer from https://www.python.org/downloads/
    echo        and tick "Add Python to PATH" on the first installer screen.
    pause
    exit /b 1
)

for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo     Python %PYVER% detected.

python -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)"
if errorlevel 1 (
    echo ERROR: Python %PYVER% found, but Optima needs 3.11 or newer.
    pause
    exit /b 1
)

:: ---- 2. Virtual environment ----------------------------------------------
if not exist .venv (
    echo ==^> Creating virtual environment in .venv\
    python -m venv .venv
) else (
    echo     Virtual environment already exists -- reusing
)

call .venv\Scripts\activate.bat

:: ---- 3. Dependencies -----------------------------------------------------
echo ==^> Installing dependencies (this takes 30-60 seconds first run)
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

:: ---- 4. Desktop launcher -------------------------------------------------
set "LAUNCHER=%USERPROFILE%\Desktop\Optima.bat"
echo @echo off                                       > "%LAUNCHER%"
echo cd /d "%PROJECT_DIR%"                          >> "%LAUNCHER%"
echo call .venv\Scripts\activate.bat                >> "%LAUNCHER%"
echo python run.py                                  >> "%LAUNCHER%"
echo pause                                          >> "%LAUNCHER%"
echo ==^> Wrote Windows launcher --^> %LAUNCHER%
echo     Double-click that file to launch Optima.

echo.
echo ==^> Done. Launch Optima with:
echo         cd /d "%PROJECT_DIR%"
echo         call .venv\Scripts\activate.bat
echo         python run.py
echo.
echo     Or use the launcher created above.

pause
endlocal
