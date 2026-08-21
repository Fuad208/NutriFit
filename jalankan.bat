@echo off
REM Menjalankan NutriFit memakai Python di dalam .venv, apa pun isi PATH.
REM
REM Di komputer ini ada TIGA lingkungan Python yang punya streamlit:
REM   1. .venv proyek ini            - Python 3.11, streamlit 1.61, LENGKAP
REM   2. ..\..\NutriFit\.venv        - salinan proyek lama, TANPA argon2-cffi
REM   3. --user pada Python 3.12     - streamlit 1.46, tanpa argon2 & psycopg
REM
REM Menjalankan lewat "streamlit run" biasa bisa mengenai nomor 2 atau 3 dan
REM berhenti dengan "ModuleNotFoundError: No module named 'argon2'".
REM
REM Berkas ini memanggil streamlit.exe milik venv secara langsung, sehingga
REM PATH tidak lagi menentukan.

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

echo Menjalankan NutriFit dari .venv ...
".venv\Scripts\streamlit.exe" run app.py %*

endlocal
