@echo off
REM Crea el acceso directo de AI Hub en el escritorio.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0crear_acceso_directo.ps1"
pause
