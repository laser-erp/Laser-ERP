# Запуск Laser ERP (PowerShell)
# Лучше запускать run.bat двойным щелчком или из CMD
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "Ошибка: виртуальное окружение не найдено. Запустите: python -m venv .venv"
    Read-Host "Нажмите Enter"
    exit 1
}

Write-Host "Запуск сервера Laser ERP..."
$env:INVOICE_OCR_ENABLED = "1"
$env:INVOICE_OCR_TESSERACT_CMD = "E:\Виртуальный сервер\Tessersct\tesseract.exe"
Write-Host "OCR включён. Tesseract: $env:INVOICE_OCR_TESSERACT_CMD"
Write-Host "Откройте в браузере: http://127.0.0.1:8000/admin/"
Write-Host "Остановка: Ctrl+C"
Write-Host ""

& $py manage.py runserver 127.0.0.1:8000
Read-Host "Нажмите Enter для выхода"
