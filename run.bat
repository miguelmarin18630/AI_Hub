@echo off
REM Arranca AI Hub mostrando la consola (util para ver errores).
cd /d "%~dp0"
python AIHub.pyw %*
if errorlevel 1 (
    echo.
    echo La aplicacion termino con errores.
    pause
)
