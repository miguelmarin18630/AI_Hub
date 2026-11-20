@echo off
REM Abre el tunel de Cloudflare hacia AI Hub Web (http://127.0.0.1:8765).
REM Deja esta ventana abierta mientras quieras que el sitio sea accesible.
REM Para cerrarlo: Ctrl + C o cerrar la ventana.
cd /d "%~dp0"
cloudflared tunnel run aihub
echo.
echo El tunel se ha cerrado.
pause
