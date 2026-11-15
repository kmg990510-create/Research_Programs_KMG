@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Python virtual environment not found at "%~dp0.venv\Scripts\python.exe".
    echo Please create .venv and install dependencies first.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m streamlit run fet_gui\Run.py %*
endlocal
