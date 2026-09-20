@echo off
chcp 65001 >nul
echo Выключаю системный прокси (прямой интернет)...
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyEnable /t REG_DWORD /d 0 /f >nul
setx HTTP_PROXY "" >nul
setx HTTPS_PROXY "" >nul
setx ALL_PROXY "" >nul
echo.
echo Готово. Интернет снова напрямую (без Happ).
echo При необходимости перезапустите Chrome и Cursor.
echo.
pause
