@echo off
setlocal
cd /d "%~dp0"
set "KMG_PREVIEW_PY=%USERPROFILE%\Desktop\Research_Programs_KMG\FET_analysis\.venv\Scripts\python.exe"
if exist "%KMG_PREVIEW_PY%" (
  "%KMG_PREVIEW_PY%" -m streamlit run app.py --server.address 127.0.0.1 --server.port 8766 --browser.gatherUsageStats false
) else (
  py -m streamlit run app.py --server.address 127.0.0.1 --server.port 8766 --browser.gatherUsageStats false
)
if errorlevel 1 pause
