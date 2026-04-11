@echo off
cd /d "%~dp0"
set ELECTRON_RUN_AS_NODE=
set ELECTRON_NO_ATTACH_CONSOLE=
start "" "%~dp0node_modules\electron\dist\electron.exe" .