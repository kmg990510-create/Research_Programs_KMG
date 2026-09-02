@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv\Scripts\python.exe was not found.
    echo Run setup first:
    echo   python -m venv .venv
    echo   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
)

echo Starting MoS2 Raman/PL Analysis Viewer...
echo Close this window to stop the GUI server.
echo.

".venv\Scripts\python.exe" -m streamlit run gui\Main.py

endlocal
