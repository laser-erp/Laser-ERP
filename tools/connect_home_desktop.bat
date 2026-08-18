@echo off
REM На НОУТБУКЕ: двойной клик — откроется RDP на домашний ПК (полный рабочий стол + этот Cursor/чат).
REM Нужен ключ: scp root@aptown11.fvds.ru:/root/home-pc-ssh/id_ed25519_home %USERPROFILE%\.ssh\id_ed25519_home

set KEY=%USERPROFILE%\.ssh\id_ed25519_home
set VPS=aptown11.fvds.ru
set LOCAL_RDP=13389

if not exist "%KEY%" (
  echo Сначала скопируйте ключ:
  echo   scp root@%VPS%:/root/home-pc-ssh/id_ed25519_home %KEY%
  pause
  exit /b 1
)

echo Поднимаю туннель RDP (окно ssh оставьте открытым)...
start "Home RDP tunnel" ssh -i "%KEY%" -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new -N -L %LOCAL_RDP%:127.0.0.1:3389 root@%VPS%
timeout /t 3 /nobreak >nul
echo Подключение к рабочему столу домашнего ПК...
mstsc /v:127.0.0.1:%LOCAL_RDP%
