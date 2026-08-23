"""Pemeriksaan lingkungan sebelum aplikasi dijalankan.

Mengubah galat impor yang menunjuk berkas yang sebenarnya tidak bermasalah
menjadi instruksi cara menjalankan aplikasi lewat venv yang benar.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

# Paket yang tidak ada di instalasi --user Python 3.12, sehingga paling cepat
# membedakan "salah lingkungan" dari "venv rusak".
PAKET_WAJIB = {
    "argon2": "argon2-cffi",
    "psycopg": "psycopg[binary]",
    "pandas": "pandas",
    "sklearn": "scikit-learn",
}

AKAR = Path(__file__).resolve().parent.parent
VENV_PYTHON = AKAR / ".venv" / "Scripts" / "python.exe"
VENV_STREAMLIT = AKAR / ".venv" / "Scripts" / "streamlit.exe"


def paket_hilang() -> list[str]:
    """Daftar nama paket wajib (nama pip) yang belum terpasang di lingkungan aktif."""
    return [
        nama_pip
        for modul, nama_pip in PAKET_WAJIB.items()
        if importlib.util.find_spec(modul) is None
    ]


def pesan_lingkungan(hilang: list[str], berkas_app: str) -> str:
    """Instruksi konkret, bukan sekadar keluhan."""
    baris = [
        "### Aplikasi dijalankan dengan Python yang salah",
        "",
        f"Paket wajib berikut tidak ada di lingkungan ini: **{', '.join(hilang)}**.",
        "",
        f"Python yang sedang dipakai:  \n`{sys.executable}`",
    ]
    if VENV_STREAMLIT.exists():
        baris += [
            "",
            "Seluruh paket itu **sudah terpasang** di venv proyek. Hentikan proses ini "
            "(Ctrl+C di terminal), lalu jalankan ulang dengan salah satu cara berikut.",
            "",
            "**Cara tercepat** — tanpa mengaktifkan apa pun:",
            "```powershell",
            f'cd "{AKAR}"',
            f".\\.venv\\Scripts\\streamlit.exe run {berkas_app}",
            "```",
            "",
            "**Atau aktifkan venv-nya dulu** (prompt akan diawali `(.venv)`):",
            "```powershell",
            f'cd "{AKAR}"',
            ".\\.venv\\Scripts\\Activate.ps1",
            f"streamlit run {berkas_app}",
            "```",
            "",
            f"**Atau klik dua kali** berkas `jalankan.bat` di folder proyek.",
            "",
            "---",
            "",
            "Di VS Code: `Ctrl+Shift+P` → **Python: Select Interpreter** → pilih yang "
            "berada di `.venv\\Scripts\\python.exe`, lalu buka terminal baru.",
        ]
    else:
        baris += [
            "",
            "Venv proyek belum dibuat. Jalankan sekali di folder proyek:",
            "```powershell",
            "py -3.11 -m venv .venv",
            ".\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt",
            "```",
        ]
    return "\n".join(baris)


def pastikan_lingkungan(berkas_app: str = "app.py") -> None:
    """Hentikan aplikasi dengan pesan yang jelas bila lingkungannya salah.

    Dipanggil PALING AWAL di app.py dan admin_app.py -- sebelum impor apa pun
    yang membutuhkan paket tersebut, karena setelah itu sudah terlambat.
    """
    hilang = paket_hilang()
    if not hilang:
        return

    pesan = pesan_lingkungan(hilang, berkas_app)
    try:
        import streamlit as st
    except ModuleNotFoundError:
        print(pesan, file=sys.stderr)
        raise SystemExit(1)

    st.error(pesan)
    st.stop()
