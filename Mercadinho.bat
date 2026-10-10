@echo off
REM Launcher do Sistema do Mercadinho (retail-pos-python) para Windows.
REM Usa o Python do ambiente virtual .venv do projeto, se existir.
setlocal
set "DIR=%~dp0"
cd /d "%DIR%"

if exist "%DIR%.venv\Scripts\python.exe" (
    "%DIR%.venv\Scripts\python.exe" "%DIR%app.py" %*
) else (
    python "%DIR%app.py" %*
)
