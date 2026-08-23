"""Loader data (dataset gym/food/exercise) dan tutorial latihan, dengan cache."""

from __future__ import annotations

import json
import time

import streamlit as st

from src.paths import DATA_DIR, TRAINING_DETAIL_DIR  # noqa: F401  (dipakai ulang oleh views/workout.py)
from src.recommender import load_datasets


TRAINING_DETAIL_PATH = TRAINING_DETAIL_DIR / "data" / "exercises.json"

# --------------------------------------------------------------------------- #
# Penanda versi dataset
# --------------------------------------------------------------------------- #
# Isi berkas penanda dipakai sebagai BAGIAN DARI KUNCI CACHE, sehingga perubahan
# dataset oleh admin otomatis membuat pemanggilan berikutnya meleset dari cache
# di proses mana pun. Panel admin dan aplikasi pengguna adalah dua proses
# terpisah, jadi memanggil .clear() saja tidak cukup.
# Alasan memakai berkas, bukan kueri database: docs/catatan-desain.md bagian 16.
DATASET_VERSION_PATH = DATA_DIR / ".dataset_version"


def versi_dataset() -> str:
    """Penanda versi dataset saat ini; string kosong bila belum pernah diubah."""
    try:
        return DATASET_VERSION_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def tandai_dataset_berubah() -> None:
    """Naikkan penanda versi supaya SETIAP proses memuat ulang dataset.

    Kegagalan menulis diabaikan: tanpa penanda hasilnya tetap benar setelah aplikasi
    dijalankan ulang.
    """
    try:
        DATASET_VERSION_PATH.parent.mkdir(parents=True, exist_ok=True)
        sementara = DATASET_VERSION_PATH.with_suffix(".tmp")
        sementara.write_text(str(time.time_ns()), encoding="utf-8")
        sementara.replace(DATASET_VERSION_PATH)
    except OSError:
        pass


def bersihkan_cache_dataset() -> None:
    """Buang salinan dataset di memori proses INI saja.

    Berbeda dari `tandai_dataset_berubah()`, fungsi ini tidak memaksa proses lain ikut
    memuat ulang.
    """
    _muat_dataset.clear()


# max_entries dibatasi supaya salinan dataset dari versi terdahulu tidak menumpuk di
# memori setiap kali admin menyimpan perubahan.
@st.cache_data(show_spinner=False, max_entries=2)
def _muat_dataset(versi: str):
    """Muat dataset untuk satu versi penanda; hasilnya di-cache lintas rerun."""
    return load_datasets()


def get_data():
    """Muat dataset member, makanan, dan latihan sesuai versi dataset terbaru."""
    return _muat_dataset(versi_dataset())


@st.cache_data(show_spinner=False)
def load_training_tutorials() -> list[dict]:
    """Baca daftar tutorial latihan dari dataProgramTraining/data/exercises.json."""
    if not TRAINING_DETAIL_PATH.exists():
        return []
    with TRAINING_DETAIL_PATH.open("r", encoding="utf-8") as file:
        data = json.load(file)
    return data if isinstance(data, list) else []
