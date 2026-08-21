"""Halaman profil pengguna."""

from __future__ import annotations

import streamlit as st

from datetime import date

from src.database import load_users, save_users

from ..core.state import calculate_age_from_birth_date, current_user, hash_password, migrate_users, parse_birth_date


def profile_view() -> None:
    """Halaman profil: ubah nama, tanggal lahir, jenis kelamin, dan password akun."""
    user = current_user()
    if not user:
        st.error("Data pengguna tidak ditemukan.")
        return

    st.markdown('<div class="brand">Profile</div>', unsafe_allow_html=True)
    st.caption("Kelola informasi akun yang sedang digunakan.")

    email = st.session_state.current_user
    birth_date = parse_birth_date(user.get("birth_date", date(2000, 1, 1)))
    gender_options = {"Laki-laki": "Male", "Perempuan": "Female"}
    current_gender = user.get("gender", "Male")
    gender_labels = list(gender_options)
    gender_index = 0 if current_gender == "Male" else 1

    # Sengaja TIDAK memakai st.form. Di dalam form, tidak ada widget yang
    # dijalankan ulang sampai tombol simpan ditekan, sehingga kolom "Umur" tetap
    # menampilkan angka lama walaupun tanggal lahirnya sudah diganti -- persis
    # gejala yang dilaporkan. Di luar form, mengganti tanggal memicu rerun dan
    # umurnya ikut berubah seketika.
    col1, col2 = st.columns(2)
    with col1:
        name = st.text_input("Nama Lengkap", value=user.get("name", ""))
        st.text_input("Email", value=user.get("email", email), disabled=True)
        birth_date_value = st.date_input(
            "Tanggal Lahir",
            value=birth_date,
            min_value=date(1940, 1, 1),
            max_value=date.today(),
        )
    with col2:
        st.number_input(
            "Umur",
            value=calculate_age_from_birth_date(birth_date_value),
            min_value=0,
            max_value=120,
            disabled=True,
            help="Dihitung otomatis dari tanggal lahir.",
        )
        gender_label = st.radio("Jenis Kelamin", gender_labels, index=gender_index, horizontal=True)
        new_password = st.text_input("Password Baru", type="password", placeholder="Kosongkan jika tidak diganti")
        confirm_password = st.text_input("Konfirmasi Password Baru", type="password")

    submitted = st.button("Simpan Perubahan", use_container_width=True, type="primary")

    if submitted:
        if not name.strip():
            st.error("Nama lengkap wajib diisi.")
            return
        if new_password and new_password != confirm_password:
            st.error("Konfirmasi password baru tidak sesuai.")
            return

        users = migrate_users(load_users())
        saved_user = users.get(email)
        if not saved_user:
            st.error("Data pengguna tidak ditemukan.")
            return

        saved_user["name"] = name.strip()
        saved_user["birth_date"] = birth_date_value.isoformat()
        saved_user["gender"] = gender_options[gender_label]
        if new_password:
            saved_user["password"] = hash_password(new_password)
            saved_user.pop("password_hash", None)

        save_users(users)
        st.session_state.users = migrate_users(load_users())
        st.success("Profile berhasil diperbarui.")
        st.rerun()
