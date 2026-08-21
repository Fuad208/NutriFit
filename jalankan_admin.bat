@echo off
REM Menjalankan panel admin NutriFit memakai Python di dalam .venv.
REM Lihat keterangan lengkap di jalankan.bat.

setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\streamlit.exe" (
    echo.
    echo   Venv belum ada atau belum lengkap.
    echo   Jalankan sekali perintah berikut di folder ini:
    echo.
    echo       py -3.11 -m venv .venv
    echo       .venv\Scripts\python.exe -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

echo Menjalankan NutriFit Admin dari .venv ...
".venv\Scripts\streamlit.exe" run admin_app.py --server.port 8502 %*

endlocal
