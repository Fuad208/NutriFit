"""Navigasi sidebar aplikasi."""

from __future__ import annotations

import streamlit as st

from .state import current_role


# Halaman yang tidak punya item sendiri di sidebar. Tanpa ini, saat user
# membukanya tidak ada satu pun item yang aktif dan mereka kehilangan konteks
# sedang di mana -- dipakai untuk menampilkan penanda lokasi di bawah nav.
SUBPAGE_LABELS = {
    "ForgotPassword": "Lupa Password",
    "Workout Tutorial": "Tutorial Latihan",
}


def render_nav(items: list[tuple[str, str]]) -> None:
    """Render daftar navigasi sidebar.

    Halaman yang sedang dibuka dirender sebagai pil aktif (bukan tombol),
    sisanya sebagai tombol biasa. Dipakai bersama oleh menu sebelum dan
    sesudah login supaya penanda "Anda di sini" konsisten di kedua kondisi.
    """
    for page, label in items:
        if page == st.session_state.page:
            st.sidebar.markdown(f'<div class="sidebar-active">{label}</div>', unsafe_allow_html=True)
            st.sidebar.markdown('<div class="sidebar-spacer"></div>', unsafe_allow_html=True)
            continue
        if st.sidebar.button(label, key=f"nav_{page}", use_container_width=True):
            st.session_state.page = page
            st.rerun()

    current = st.session_state.page
    if current in SUBPAGE_LABELS and current not in {page for page, _ in items}:
        st.sidebar.markdown(
            f'<div class="sidebar-subpage">Anda di: {SUBPAGE_LABELS[current]}</div>',
            unsafe_allow_html=True,
        )


def sidebar() -> None:
    """Render sidebar: brand, menu navigasi sesuai status login, dan tombol logout."""
    st.sidebar.markdown(
        """
        <div class="sidebar-brand">NutriFit</div>
        <div class="sidebar-subtitle">Healthy Living</div>
        """,
        unsafe_allow_html=True,
    )

    if st.session_state.authenticated:
        render_nav(
            [
                ("Home", "Home"),
                ("Profile", "Profile"),
                ("Calorie Calculator", "Hitung Kalori"),
                ("Meal Recommendation", "Rekomendasi Menu"),
                ("Workout Recommendation", "Rekomendasi Latihan"),
            ]
        )
        st.sidebar.markdown('<div class="sidebar-divider"></div>', unsafe_allow_html=True)
        st.sidebar.caption(f"Role: {current_role()}")
        if st.sidebar.button("Logout", key="sidebar_logout", use_container_width=True):
            st.session_state.authenticated = False
            st.session_state.current_user = None
            st.session_state.page = "Login"
            st.session_state.nutrition = None
            st.session_state.profile = None
            st.rerun()
    else:
        render_nav([("Login", "Masuk"), ("Register", "Daftar")])
