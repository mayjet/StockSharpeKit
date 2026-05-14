@echo off
setlocal enabledelayedexpansion

REM ============================================
REM  Local dev environment setup (uv venv)
REM  Streamlit app + Jupyter notebook
REM ============================================

set "VENV_DIR=.venv"
set "UV_CMD=uv"

REM Move to project root (2 levels up from build\windows)
cd /d "%~dp0..\.."
echo [setup] Project root: %cd%

REM ============================================
REM  Step 1: Check Python
REM ============================================
echo.
echo [1/6] Checking Python...

set "PY_CMD="

python --version >nul 2>&1
if not errorlevel 1 (
    set "PY_CMD=python"
    goto :python_found
)

python3 --version >nul 2>&1
if not errorlevel 1 (
    set "PY_CMD=python3"
    goto :python_found
)

py --version >nul 2>&1
if not errorlevel 1 (
    set "PY_CMD=py"
    goto :python_found
)

REM Check common install locations
for %%D in (
    "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    "%ProgramFiles%\Python313\python.exe"
    "%ProgramFiles%\Python312\python.exe"
    "%ProgramFiles%\Python311\python.exe"
    "%ProgramFiles%\Python310\python.exe"
) do (
    if exist %%D (
        set "PY_CMD=%%~D"
        goto :python_found
    )
)

REM Python not found - try winget auto-install
echo [setup] Python not found. Attempting install via winget...
where winget >nul 2>&1
if errorlevel 1 goto :no_python

winget install --id Python.Python.3.11 --accept-source-agreements --accept-package-agreements
if errorlevel 1 goto :no_python

REM Refresh PATH for this session
for /f "tokens=2*" %%A in ('reg query "HKCU\Environment" /v Path 2^>nul') do set "PATH=%%B;%PATH%"
for /f "tokens=2*" %%A in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v Path 2^>nul') do set "PATH=%%B;%PATH%"

python --version >nul 2>&1
if not errorlevel 1 (
    set "PY_CMD=python"
    goto :python_found
)

echo [WARN]  Python was installed but not found in current session.
echo         Close this terminal, open a new one, and run this script again.
exit /b 1

:no_python
echo [ERROR] Python is not installed and could not be auto-installed.
echo         Install manually from: https://www.python.org/downloads/
echo         Or via winget: winget install Python.Python.3.11
exit /b 1

:python_found
for /f "tokens=*" %%V in ('!PY_CMD! --version 2^>nul') do echo [setup] !PY_CMD! - %%V found.

REM ============================================
REM  Step 2: Check / Install uv
REM ============================================
echo.
echo [2/6] Checking uv...

where uv >nul 2>&1
if not errorlevel 1 goto :uv_found

echo [setup] uv not found. Installing via pip...

!PY_CMD! -m pip install uv
if errorlevel 1 goto :uv_install_failed
echo [setup] uv package installed.

REM Check if uv is now in PATH
where uv >nul 2>&1
if not errorlevel 1 goto :uv_found

REM uv installed but not in PATH - find it via Python sysconfig
echo [setup] uv not in PATH. Searching...
for /f "delims=" %%P in ('!PY_CMD! -c "import sysconfig; print(sysconfig.get_path('scripts'))" 2^>nul') do (
    if exist "%%P\uv.exe" (
        set "UV_CMD=%%P\uv.exe"
        echo [setup] Found: %%P\uv.exe
        goto :uv_found
    )
)

echo [ERROR] uv was installed but not found in PATH.
echo         Close this terminal, open a new one, and try again.
exit /b 1

:uv_install_failed
echo [ERROR] Failed to install uv.
echo         Try manually: pip install uv
exit /b 1

:uv_found
for /f "tokens=*" %%V in ('"!UV_CMD!" --version 2^>nul') do echo [setup] %%V found.

REM ============================================
REM  Step 3: Remove existing venv
REM ============================================
echo.
echo [3/6] Preparing venv directory...

if not exist "%VENV_DIR%" goto :no_existing_venv

echo [setup] Removing existing venv...
rmdir /s /q "%VENV_DIR%" 2>nul

if not exist "%VENV_DIR%" goto :venv_removed
echo [WARN]  Failed to remove .venv directory.
echo         A process may be using it (e.g. Jupyter, Python).
echo         Close all related processes and try again.
exit /b 1

:venv_removed
echo [setup] Old venv removed.
goto :step4

:no_existing_venv
echo [setup] No existing venv. Clean start.

REM ============================================
REM  Step 4: Create venv
REM ============================================
:step4
echo.
echo [4/6] Creating virtual environment...

"!UV_CMD!" venv "%VENV_DIR%"
if errorlevel 1 goto :venv_create_failed

if not exist "%VENV_DIR%\Scripts\activate.bat" goto :venv_corrupt

call "%VENV_DIR%\Scripts\activate.bat"
echo [setup] venv activated.
goto :step5

:venv_create_failed
echo [ERROR] Failed to create venv.
echo         Possible causes:
echo           - No internet connection (uv may need to download Python)
echo           - Disk full
echo           - Antivirus blocking
exit /b 1

:venv_corrupt
echo [ERROR] venv was created but activate.bat is missing.
echo         The venv may be corrupted. Delete .venv and try again.
exit /b 1

REM ============================================
REM  Step 5: Install app dependencies
REM ============================================
:step5
echo.
echo [5/6] Installing app dependencies...

if not exist "requirements.txt" goto :no_requirements

"!UV_CMD!" pip install -r requirements.txt
if errorlevel 1 goto :requirements_failed
echo [setup] App dependencies installed.
goto :step6

:no_requirements
echo [ERROR] requirements.txt not found in %cd%
echo         Make sure this script is located in build\windows\
exit /b 1

:requirements_failed
echo [ERROR] Failed to install dependencies from requirements.txt.
echo         Possible causes:
echo           - No internet connection
echo           - Package version conflict
echo         Check the error messages above.
exit /b 1

REM ============================================
REM  Step 6: Install Jupyter packages (optional)
REM ============================================
:step6
echo.
echo [6/6] Installing Jupyter packages (optional)...

"!UV_CMD!" pip install jupyter ipykernel scikit-learn
if errorlevel 1 goto :jupyter_failed

echo [setup] Jupyter packages installed.

REM --- Register Jupyter kernel ---
where jupyter >nul 2>&1
if errorlevel 1 goto :no_jupyter_cmd

for %%I in ("%cd%") do set "DIR_NAME=%%~nxI"
set "KERNEL_NAME=!DIR_NAME!_kernel"
echo [setup] Registering kernel: !KERNEL_NAME!

!PY_CMD! -m ipykernel install --user --name "!KERNEL_NAME!" --display-name "Python (!VENV_DIR!)" >nul 2>&1
if errorlevel 1 goto :kernel_failed

echo [setup] Kernel registered: !KERNEL_NAME!
goto :done

:kernel_failed
echo [WARN]  Kernel registration failed. You can register manually later:
echo         python -m ipykernel install --user --name "!KERNEL_NAME!"
goto :done

:no_jupyter_cmd
echo [WARN]  jupyter command not found after install. Kernel registration skipped.
goto :done

:jupyter_failed
echo [WARN]  Jupyter packages failed to install.
echo         The app will still work. Jupyter notebooks will not be available.

REM ============================================
REM  Done
REM ============================================
:done
echo.
echo ============================================
echo  Setup complete!
echo  Activate : %VENV_DIR%\Scripts\activate.bat
echo  Run app  : streamlit run app.py
echo  Jupyter  : jupyter notebook
echo ============================================

endlocal
exit /b 0
