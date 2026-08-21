"""Lokasi folder proyek NutriFit.

Semua path berkas (.env, data/, dataProgramTraining/, assets/) dihitung dari
folder proyek ini, BUKAN dari folder tempat perintah dijalankan.

Alasannya konkret: sebelumnya path-nya relatif ke cwd, jadi menjalankan
`streamlit run NutriFit/app.py` dari folder induk membuat `.env` tidak
ditemukan -- dan tanpa .env, kredensial Supabase ikut hilang sehingga aplikasi
gagal menyambung ke database padahal seluruh datanya utuh.

Dengan anchor ini aplikasi berperilaku sama dari folder mana pun dijalankan.
"""

from __future__ import annotations

from pathlib import Path


# src/paths.py -> src/ -> NutriFit/
PROJECT_ROOT = Path(__file__).resolve().parent.parent

ENV_PATH = PROJECT_ROOT / ".env"
DATA_DIR = PROJECT_ROOT / "data"
TRAINING_DETAIL_DIR = PROJECT_ROOT / "dataProgramTraining"

# Aset statis yang ikut disimpan di repositori (animasi Lottie & pemutarnya).
# Isinya diunduh oleh schema_data/fetch_lottie_assets.py, bukan dibuat tangan;
# lihat assets/lottie/SUMBER.md untuk asal dan lisensinya.
ASSETS_DIR = PROJECT_ROOT / "assets"
