"""Halaman login, registrasi, verifikasi email, & lupa password."""

from __future__ import annotations

import html

import streamlit as st

from datetime import date
from uuid import uuid4

from src.database import load_users, save_users
from src.emailing import EmailNotConfiguredError
from src.paths import ASSETS_DIR

from ..core.state import (
    confirm_email_verification,
    confirm_password_reset,
    hash_password,
    is_gmail_address,
    landing_page_for_user,
    migrate_users,
    password_needs_upgrade,
    restore_user_context,
    start_email_verification,
    start_password_reset,
    upgrade_password_hash,
    verify_password,
    VERIFICATION_TOKEN_HOURS,
)


HERO_TEKS = (
    "Pantau nutrisi harian Anda, capai target kebugaran, dan ubah gaya hidup "
    "Anda lewat rencana menu dan latihan yang dipersonalisasi."
)

# Ilustrasi kolom hero: satu berkas per halaman, disimpan di dalam proyek.
# Tingginya dipatok lewat .hero-image di core/styles.py -- lihat komentar di
# sana soal halaman login yang bisa bergetar kalau tinggi gambar ikut lebarnya.
HERO_GAMBAR = {
    "Login": ASSETS_DIR / "hero" / "hero_login.jpg",
    "Register": ASSETS_DIR / "hero" / "hero_register.jpg",
}


def auth_view() -> None:
    """Pintu masuk halaman non-login: pilih form daftar, masuk, lupa sandi, atau konfirmasi dari tautan email."""
    # Kalau user datang dari link email (verifikasi / reset password), query
    # param ini lebih diprioritaskan daripada session_state.page biasa --
    # sesi mereka baru (buka link dari email), jadi page masih default "Login".
    query_params = st.query_params
    verify_token = query_params.get("verify")
    reset_token = query_params.get("reset")
    dari_email = bool(verify_token or reset_token)

    # Halaman daftar menaruh formulir di KIRI dan animasi di kanan; halaman
    # lainnya sebaliknya. Pergantian sisi ini disengaja: berpindah antara masuk
    # dan daftar jadi terasa sebagai perpindahan halaman, bukan sekadar isi
    # kolom yang berganti diam-diam.
    gambar_di_kanan = not dari_email and st.session_state.page == "Register"

    kolom_a, kolom_b = st.columns(2, gap="large")
    if gambar_di_kanan:
        kolom_form, kolom_gambar = kolom_a, kolom_b
    else:
        kolom_gambar, kolom_form = kolom_a, kolom_b

    with kolom_gambar:
        render_hero("Register" if gambar_di_kanan else "Login")

    with kolom_form:
        if verify_token:
            email_verification_confirm_view(verify_token)
        elif reset_token:
            password_reset_confirm_view(reset_token)
        elif st.session_state.page == "Register":
            register_form()
        elif st.session_state.page == "ForgotPassword":
            forgot_password_form()
        else:
            login_form()


def render_hero(halaman: str) -> None:
    """Kolom identitas: nama aplikasi, satu kalimat pengantar, lalu ilustrasi."""
    st.markdown(
        f"""
        <div class="hero">
            <div class="brand">NutriFit</div>
            <p class="subtle">{HERO_TEKS}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    berkas = HERO_GAMBAR.get(halaman)
    if not berkas or not berkas.exists():
        # Gambar hilang bukan alasan menjatuhkan halaman masuk. Kolomnya
        # dibiarkan kosong; formulir di sebelahnya tetap bisa dipakai.
        return

    # st.image, bukan <img src="data:..."> di dalam st.markdown: berkasnya
    # disajikan lewat penyimpanan media Streamlit, jadi isinya tidak perlu
    # disisipkan ulang ke dalam HTML pada setiap rerun.
    with st.container(key="hero_gambar"):
        st.image(str(berkas), width="stretch")


def judul_auth(judul: str, keterangan: str) -> None:
    """Render judul besar dan keterangan singkat pada halaman autentikasi."""
    st.markdown(
        f'<div class="auth-title">{html.escape(judul)}</div>'
        f'<p class="auth-sub">{html.escape(keterangan)}</p>',
        unsafe_allow_html=True,
    )


def label_isian(teks: str, *, wajib: bool = False) -> str:
    """Label buatan sendiri, dipakai bersama label_visibility="collapsed".

    Streamlit tidak punya penanda "wajib diisi" pada label widget-nya,
    sedangkan rancangan halaman masuk memintanya sebagai bintang merah.
    """
    bintang = '<span class="wajib">*</span>' if wajib else ""
    return f'<div class="auth-label">{html.escape(teks)}{bintang}</div>'


def register_form() -> None:
    """Formulir pendaftaran akun baru berikut validasi dan pengiriman email verifikasi."""
    judul_auth("Buat Akun Baru", "Buat akun untuk mulai program.")
    with st.container(key="kartu_daftar"):
        with st.form("register_form"):
            name = st.text_input("Nama Lengkap", placeholder="Budi Santoso")
            email = st.text_input("Email", placeholder="nama.kamu@gmail.com")
            password = st.text_input("Kata Sandi", type="password")
            confirm_password = st.text_input("Konfirmasi Kata Sandi", type="password")
            birth_date = st.date_input("Tanggal Lahir", value=date(2000, 12, 25), min_value=date(1940, 1, 1), max_value=date.today())
            # Nilai disimpan tetap "Male"/"Female" karena dipakai model rekomendasi
            # sebagai fitur kategorikal; hanya labelnya yang di-Indonesia-kan.
            gender = st.radio(
                "Jenis Kelamin",
                ["Male", "Female"],
                horizontal=True,
                format_func=lambda value: "Laki-laki" if value == "Male" else "Perempuan",
            )
            agree = st.checkbox("Saya menyetujui Syarat dan Ketentuan yang berlaku")
            submitted = st.form_submit_button("Daftar", use_container_width=True)

    if submitted:
        st.session_state.users = migrate_users(load_users())
        email_clean = (email or "").strip().lower()
        if not name or not email_clean or not password:
            st.error("Lengkapi semua kolom yang wajib diisi.")
        elif password != confirm_password:
            st.error("Konfirmasi kata sandi tidak cocok.")
        elif not is_gmail_address(email_clean):
            st.error("Email harus menggunakan alamat Gmail asli (@gmail.com).")
        elif email_clean in st.session_state.users:
            st.error("Email ini sudah terdaftar.")
        elif not agree:
            st.error("Anda harus menyetujui Syarat dan Ketentuan.")
        else:
            st.session_state.users[email_clean] = {
                "user_id": str(uuid4()),
                "name": name,
                "email": email_clean,
                # Pendaftaran lama menulis hash ke kolom `password`; sekarang
                # semuanya memakai `password_hash` supaya cuma ada satu sumber
                # kebenaran (lihat stored_password_hash di core/state.py).
                "password": None,
                "password_hash": hash_password(password),
                "role": "user",
                "birth_date": birth_date.isoformat(),
                "gender": gender,
                "profile": None,
                "nutrition": None,
                "auth_provider": "local",
                "email_verified": False,
            }
            save_users(st.session_state.users)
            try:
                start_email_verification(email_clean)
            except EmailNotConfiguredError:
                st.warning(
                    "Akun dibuat, tapi email verifikasi belum bisa dikirim karena SMTP belum "
                    "dikonfigurasi di .env. Hubungi admin, atau isi SMTP_HOST/SMTP_USER/SMTP_PASSWORD."
                )
            else:
                st.success(
                    f"Akun berhasil dibuat. Kami sudah mengirim link verifikasi ke {email_clean} "
                    f"(berlaku {VERIFICATION_TOKEN_HOURS} jam). Buka email Anda dan klik link "
                    "tersebut sebelum login."
                )
            st.session_state.page = "Login"

    # Jalan kembali ke halaman masuk. Tidak ada di rancangan, tapi tanpa ini
    # satu-satunya jalan pulang adalah menu sidebar -- dan orang yang salah
    # menekan "Daftar" akan mencarinya di dekat formulir, bukan di sidebar.
    baris_tautan("Sudah punya akun?", "Masuk", "ke_masuk", "Login")


def baris_tautan(teks: str, label: str, kunci: str, tujuan: str) -> None:
    """Satu baris teks dengan tombol tautan ke halaman lain."""
    with st.container(key="baris_kaki_auth"):
        kiri, kanan = st.columns(2)
        with kiri:
            st.markdown(
                f'<div class="auth-footer-teks">{html.escape(teks)}</div>',
                unsafe_allow_html=True,
            )
        with kanan:
            if st.button(label, key=kunci):
                st.session_state.page = tujuan
                # Token di URL milik alur email; menyisakannya membuat halaman
                # tujuan tetap menampilkan layar verifikasi/reset.
                st.query_params.clear()
                st.rerun()


def login_form() -> None:
    """Formulir masuk: verifikasi kredensial, pemutakhiran hash lama, lalu pemulihan konteks pengguna."""
    judul_auth("Selamat Datang Kembali", "Masukkan data akun Anda untuk masuk.")

    # Halaman ini sengaja tidak memakai st.form: tautan "Lupa Password?" harus
    # berada di antara kotak sandi dan tombol Masuk, sedangkan st.form hanya
    # mengizinkan tombol kirim di dalamnya.
    with st.container(key="kartu_masuk"):
        st.markdown(label_isian("Email", wajib=True), unsafe_allow_html=True)
        email = st.text_input(
            "Email",
            placeholder="Masukkan Email Anda",
            label_visibility="collapsed",
            key="masuk_email",
        )

        st.markdown(label_isian("Kata Sandi", wajib=True), unsafe_allow_html=True)
        password = st.text_input(
            "Kata Sandi",
            type="password",
            placeholder="Masukkan Password Anda",
            label_visibility="collapsed",
            key="masuk_sandi",
        )

        if st.button("Lupa Password?", key="ke_lupa_sandi"):
            st.session_state.page = "ForgotPassword"
            st.query_params.clear()
            st.rerun()

        submitted = st.button("Masuk", key="tombol_masuk", use_container_width=True)

    if submitted:
        st.session_state.users = migrate_users(load_users())
        email_clean = (email or "").strip().lower()
        user = st.session_state.users.get(email_clean)
        st.session_state.unverified_login_email = None
        if user and user.get("auth_provider") == "google" and not user.get("password_hash"):
            # Akun lama peninggalan fitur login Google yang sudah dihapus:
            # tidak punya password sama sekali, jadi harus lewat lupa password.
            st.error(
                "Akun ini dulu dibuat lewat Google, yang kini sudah tidak didukung. "
                "Gunakan \"Lupa Password?\" di atas untuk membuat kata sandi baru."
            )
        elif user and verify_password(user, password):
            # Status verifikasi dicek SETELAH kata sandi benar, supaya pesan
            # "belum diverifikasi" tidak membocorkan surel mana yang terdaftar.
            # Migrasi hash lama dijalankan lebih dulu karena hanya pada titik ini
            # aplikasi memegang kata sandi aslinya.
            if password_needs_upgrade(user):
                upgrade_password_hash(email_clean, password)

            if not user.get("email_verified", False):
                st.session_state.unverified_login_email = email_clean
            else:
                st.session_state.authenticated = True
                st.session_state.current_user = email_clean
                restore_user_context(email_clean)
                # Urutannya penting: restore_user_context dulu supaya
                # session_state.nutrition sudah terisi saat halaman ditentukan.
                st.session_state.page = landing_page_for_user()
                st.rerun()
        else:
            st.error("Email atau kata sandi salah.")

    # Dirender DI LUAR blok `if submitted` supaya tombolnya bertahan antar-rerun.
    # Kalau di dalam, klik tombol memicu rerun dengan submitted=False, sehingga
    # tombolnya tidak pernah dibuat lagi dan klik-nya hilang tanpa efek apa pun.
    if st.session_state.get("unverified_login_email"):
        st.error("Email Anda belum diverifikasi. Silakan cek kotak masuk untuk tautan verifikasi.")
        if st.button("Kirim ulang email verifikasi", key="kirim_ulang_verifikasi"):
            try:
                start_email_verification(st.session_state.unverified_login_email)
            except EmailNotConfiguredError:
                st.warning("SMTP belum dikonfigurasi, hubungi admin.")
            else:
                st.success("Email verifikasi baru sudah dikirim.")

    baris_tautan("Belum punya akun?", "Daftar", "ke_daftar", "Register")


def forgot_password_form() -> None:
    """Formulir permintaan tautan reset kata sandi lewat email."""
    judul_auth(
        "Lupa Kata Sandi",
        "Masukkan email akun Anda, kami akan kirimkan tautan untuk membuat "
        "kata sandi baru.",
    )
    with st.form("forgot_password_form"):
        email = st.text_input("Email", placeholder="you@gmail.com")
        submitted = st.form_submit_button("Kirim Tautan Reset", use_container_width=True)

    if submitted:
        email_clean = (email or "").strip().lower()
        if not email_clean:
            st.error("Isi email terlebih dahulu.")
        else:
            try:
                _, message = start_password_reset(email_clean)
                st.success(message)
            except EmailNotConfiguredError:
                st.warning("SMTP belum dikonfigurasi, hubungi admin.")

    if st.button("Kembali ke Halaman Masuk", use_container_width=True):
        st.session_state.page = "Login"
        st.rerun()


def email_verification_confirm_view(token: str) -> None:
    """Proses token verifikasi dari tautan email lalu tampilkan hasilnya."""
    judul_auth("Verifikasi Email", "Memeriksa tautan verifikasi dari email Anda.")
    success, message = confirm_email_verification(token)
    if success:
        st.success(message)
    else:
        st.error(message)
    if st.button("Ke Halaman Masuk", use_container_width=True):
        st.query_params.clear()
        st.session_state.page = "Login"
        st.rerun()


def password_reset_confirm_view(token: str) -> None:
    """Formulir kata sandi baru untuk pengguna yang datang dari tautan reset."""
    judul_auth("Buat Kata Sandi Baru", "Masukkan kata sandi baru untuk akun Anda.")
    with st.form("reset_password_confirm_form"):
        new_password = st.text_input("Kata Sandi Baru", type="password")
        confirm = st.text_input("Konfirmasi Kata Sandi Baru", type="password")
        submitted = st.form_submit_button("Simpan Kata Sandi Baru", use_container_width=True)

    if submitted:
        if not new_password:
            st.error("Isi kata sandi baru.")
        elif new_password != confirm:
            st.error("Konfirmasi kata sandi tidak sama.")
        else:
            success, message = confirm_password_reset(token, new_password)
            if success:
                st.success(message)
                if st.button("Ke Halaman Masuk", use_container_width=True):
                    st.query_params.clear()
                    st.session_state.page = "Login"
                    st.rerun()
            else:
                st.error(message)
