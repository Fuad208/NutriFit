"""Loader data (dataset gym/food/exercise) dan tutorial latihan, dengan cache."""

from __future__ import annotations

import json
import streamlit as st

from src.paths import TRAINING_DETAIL_DIR  # noqa: F401  (dipakai ulang oleh views/workout.py)
from src.recommender import load_datasets


TRAINING_DETAIL_PATH = TRAINING_DETAIL_DIR / "data" / "exercises.json"


@st.cache_data(show_spinner=False)
def get_data():
    """Muat dataset member, makanan, dan latihan; hasilnya di-cache lintas rerun Streamlit."""
    return load_datasets()


@st.cache_data(show_spinner=False)
def load_training_tutorials() -> list[dict]:
    """Baca daftar tutorial latihan dari dataProgramTraining/data/exercises.json."""
    if not TRAINING_DETAIL_PATH.exists():
        return []
    with TRAINING_DETAIL_PATH.open("r", encoding="utf-8") as file:
        data = json.load(file)
    return data if isinstance(data, list) else []
