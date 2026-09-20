@echo off
chcp 65001 >nul
set HTTP_PROXY=http://127.0.0.1:10809
set HTTPS_PROXY=http://127.0.0.1:10809
set ALL_PROXY=http://127.0.0.1:10809
set NO_PROXY=localhost,127.0.0.1
echo Starting Cursor via Happ proxy (data on E:)...
start "" "E:\Виртуальный сервер\cursor\Cursor.exe" --user-data-dir="E:\CursorData\user-data"
