@echo off
setlocal
if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" "%~dp0run.py" %*
) else (
  python "%~dp0run.py" %*
)
exit /b %errorlevel%
