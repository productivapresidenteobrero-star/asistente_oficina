@echo off
title Asistente Comunal
cd /d "%~dp0"
echo Iniciando Asistente Comunal...

if not exist "venv\Scripts\python.exe" (
    echo Creando entorno virtual...
    python -m venv venv
    "venv\Scripts\pip.exe" install -r requirements.txt
)
echo.
echo Abriendo navegador...
start http://localhost:8000/
echo Servidor corriendo en http://localhost:8000/
echo Presiona Ctrl+C para detener.
echo.
"venv\Scripts\python.exe" -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
echo.
pause
