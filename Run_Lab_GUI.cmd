@echo off
setlocal
cd /d "%~dp0"

set "PY_EXE="
if exist ".venv\Scripts\python.exe" set "PY_EXE=.venv\Scripts\python.exe"
if not defined PY_EXE if exist "MoS2_adsorption_sim\.venv\Scripts\python.exe" set "PY_EXE=MoS2_adsorption_sim\.venv\Scripts\python.exe"

if not defined PY_EXE (
    echo [ERROR] Python virtual environment not found ^(.venv or MoS2_adsorption_sim\.venv^).
    echo Please create a venv and install requirements.txt first.
    pause
    exit /b 1
)

"%PY_EXE%" -m streamlit run app.py %*
endlocal
