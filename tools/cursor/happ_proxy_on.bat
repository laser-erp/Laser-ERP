@echo off
chcp 65001 >nul
echo Включаю системный прокси на Happ (127.0.0.1:10809)...
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyEnable /t REG_DWORD /d 1 /f >nul
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyServer /t REG_SZ /d "127.0.0.1:10809" /f >nul
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyOverride /t REG_SZ /d "localhost;127.*;10.*;192.168.*;*.local;<local>" /f >nul
setx HTTP_PROXY "http://127.0.0.1:10809" >nul
setx HTTPS_PROXY "http://127.0.0.1:10809" >nul
setx ALL_PROXY "http://127.0.0.1:10809" >nul
echo.
echo Готово. Убедитесь, что Happ уже ПОДКЛЮЧЁН (прокси-режим).
echo Полностью перезапустите Chrome и Cursor.
echo.
pause
