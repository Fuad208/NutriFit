"""Helper kecil yang dipakai lintas-view (formatting & komponen UI reusable), dipisah ke sini supaya home.py dan calorie.py tidak saling impor."""

from __future__ import annotations

import streamlit as st

from datetime import datetime


def format_record_datetime(value) -> str:
    """Ubah timestamp ISO jadi teks tanggal-jam yang mudah dibaca (mis. 05 Mar 2026 14:30)."""
    if not value:
        return "-"
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return str(value)
    return parsed.strftime("%d %b %Y %H:%M")


def metric_card(label: str, value: str) -> None:
    """Render satu kartu metrik (label + nilai) dengan kelas CSS metric-card."""
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">{label}</div>
            <div class="metric-value">{value}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
