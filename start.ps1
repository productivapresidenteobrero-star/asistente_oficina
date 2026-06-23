Set-Location -LiteralPath $PSScriptRoot
Write-Host "Iniciando Asistente Comunal..." -ForegroundColor Green

# Verificar venv
if (-not (Test-Path "venv\Scripts\python.exe")) {
    Write-Host "Creando entorno virtual..." -ForegroundColor Yellow
    python -m venv venv
    & "venv\Scripts\pip.exe" install -r requirements.txt
}

# Matar proceso previo en puerto 8000 si existe
$process = netstat -ano | Select-String ":8000 " | Select-String "LISTENING"
if ($process) {
    $pid = $process.Line -replace '.*\s+(\d+)\s*$', '$1'
    taskkill /F /PID $pid 2>$null
    Start-Sleep -Seconds 1
}

# Abrir navegador
Start-Process "http://localhost:8000/"

Write-Host "Servidor en http://localhost:8000/ - Presiona Ctrl+C para detener" -ForegroundColor Cyan
& "venv\Scripts\python.exe" -m uvicorn backend.main:app --host 0.0.0.0 --port 8000

Read-Host "Servidor detenido. Presiona Enter para salir"
