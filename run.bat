@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo Папка проекта: %CD%
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [ОШИБКА] Виртуальное окружение не найдено.
    echo Создайте его: python -m venv .venv
    echo Затем: .venv\Scripts\pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

if not exist "manage.py" (
    echo [ОШИБКА] Файл manage.py не найден. Запустите run.bat из папки проекта.
    echo.
    pause
    exit /b 1
)

echo Проверка Django...
.venv\Scripts\python.exe -c "import django" 2>nul
if errorlevel 1 (
    echo [ОШИБКА] Django не установлен в .venv
    echo Выполните: .venv\Scripts\pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

echo Применение миграций...
.venv\Scripts\python.exe manage.py migrate --noinput
if errorlevel 1 (
    echo.
    echo [ОШИБКА] migrate не выполнен. Исправьте ошибки выше.
    pause
    exit /b 1
)

echo.
echo Запуск сервера Laser ERP (Проект 1)...
set "INVOICE_OCR_ENABLED=1"
set "INVOICE_OCR_TESSERACT_CMD=E:\Виртуальный сервер\Tessersct\tesseract.exe"
echo OCR включён. Tesseract: %INVOICE_OCR_TESSERACT_CMD%
echo.
echo Откройте в браузере: http://127.0.0.1:8000/admin/
echo Остановка сервера: Ctrl+C
echo.

.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000

if errorlevel 1 (
    echo.
    echo [Сервер завершился с ошибкой. См. текст выше.]
)
echo.
pause
