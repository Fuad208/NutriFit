from __future__ import annotations
import streamlit as st

# Harus PALING ATAS -- lihat src/preflight.py.
from src.preflight import pastikan_lingkungan

pastikan_lingkungan("admin_app.py")

from src.core.data import get_data  # noqa: E402
from src.core.state import (
    confirm_password_reset,
    current_user,
    init_state,
    migrate_users,
    start_password_reset,
    verify_password,
)

from src.core.styles import inject_css
from src.database import getenv, load_users
from src.emailing import EmailNotConfiguredError
from src.views.admin import admin_view

st.set_page_config(
    page_title="NutriFit Admin",
    page_icon="🛠️",
    layout="wide",
    initial_sidebar_state="expanded",
)

ADMIN_APP_BASE_URL_DEFAULT = "http://localhost:8502"


def _admin_base_url() -> str:
    """URL dasar panel admin, dipakai menyusun link reset password di email."""
    return getenv("ADMIN_APP_BASE_URL", ADMIN_APP_BASE_URL_DEFAULT) or ADMIN_APP_BASE_URL_DEFAULT

def admin_login_view() -> None:
    """Halaman login admin, sekaligus alur lupa password dan konfirmasi reset."""
    st.markdown("## NutriFit -- Admin Panel")
    st.caption("Khusus staf/admin. Bukan untuk akun user biasa.")
    query_params = st.query_params
    reset_token = query_params.get("reset")
    if reset_token:
        _admin_reset_confirm_view(reset_token)
        return
    mode = st.session_state.get("admin_auth_mode", "login")
    if mode == "forgot_password":
        with st.form("admin_forgot_password_form"):
            email = st.text_input("Email Admin", placeholder="")
            submitted = st.form_submit_button("Kirim Link Reset", use_container_width=True)
        if submitted:
            email_clean = (email or "").strip().lower()
            if not email_clean:
                st.error("Isi email terlebih dahulu.")
            else:
                try:
                    _, message = start_password_reset(email_clean, base_url=_admin_base_url())
                    st.success(message)
                except EmailNotConfiguredError:
                    st.warning("SMTP belum dikonfigurasi di .env, hubungi developer.")
        if st.button("Kembali ke Login", use_container_width=True):
            st.session_state.admin_auth_mode = "login"
            st.rerun()
        return

    with st.form("admin_login_form"):
        email = st.text_input("Email", placeholder="")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login", use_container_width=True)

    if submitted:
        st.session_state.users = migrate_users(load_users())
        email_clean = (email or "").strip().lower()
        user = st.session_state.users.get(email_clean)
        # Pesan generik sengaja dipakai untuk kredensial salah MAUPUN akun
        # bukan admin, supaya tidak membocorkan info akun mana yang ada/admin.
        if user and user.get("role") == "admin" and verify_password(user, password):
            st.session_state.authenticated = True
            st.session_state.current_user = email_clean
            st.rerun()
        else:
            st.error("Email, password, atau hak akses admin tidak valid.")

    if st.button("Lupa password?", use_container_width=True):
        st.session_state.admin_auth_mode = "forgot_password"
        st.rerun()


def _admin_reset_confirm_view(token: str) -> None:
    """Form pembuatan password baru ketika admin membuka link reset dari email."""
    st.subheader("Buat Password Baru")
    with st.form("admin_reset_confirm_form"):
        new_password = st.text_input("Password Baru", type="password")
        confirm = st.text_input("Konfirmasi Password Baru", type="password")
        submitted = st.form_submit_button("Simpan Password Baru", use_container_width=True)

    if submitted:
        if not new_password:
            st.error("Isi password baru.")
        elif new_password != confirm:
            st.error("Konfirmasi password tidak sama.")
        else:
            success, message = confirm_password_reset(token, new_password)
            (st.success if success else st.error)(message)
            if success and st.button("Ke halaman Login", use_container_width=True):
                st.query_params.clear()
                st.rerun()


def main() -> None:
    """Titik masuk panel admin: pastikan role admin, render sidebar, lalu halaman admin."""
    init_state()
    inject_css()
    st.session_state.setdefault("admin_auth_mode", "login")

    if not st.session_state.authenticated:
        admin_login_view()
        return

    user = current_user()
    if not user or user.get("role") != "admin":
        # Jaga-jaga: kalau role berubah di DB setelah login (mis. di-demote lewat panel user), 
        # langsung logout paksa alih-alih tetap membiarkan akses admin.
        st.session_state.authenticated = False
        st.session_state.current_user = None
        st.error("Akses admin dicabut. Silakan login ulang.")
        st.rerun()
        return

    members, foods, exercises = get_data()

    with st.sidebar:
        # Kelas yang sama dengan sidebar app user, supaya brand & tombol Logout
        # tampil konsisten di kedua aplikasi (lihat src/core/styles.py).
        st.markdown(
            """
            <div class="sidebar-brand">NutriFit</div>
            <div class="sidebar-subtitle">Admin Panel</div>
            """,
            unsafe_allow_html=True,
        )
        st.caption(f"Masuk sebagai: {user.get('name') or user.get('email')}")
        st.markdown('<div class="sidebar-divider"></div>', unsafe_allow_html=True)
        if st.button("Logout", key="sidebar_logout", use_container_width=True):
            st.session_state.authenticated = False
            st.session_state.current_user = None
            st.rerun()

    admin_view(members, foods, exercises)


if __name__ == "__main__":
    main()
