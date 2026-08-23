"""Session state, autentikasi, dan helper persist data user/rekomendasi."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import pandas as pd
import streamlit as st

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from datetime import date, datetime, timedelta
from uuid import uuid4

from src.database import CALORIE_STORE, MEAL_STORE, WORKOUT_STORE, append_record, ensure_database, latest_user_record, load_records, load_users, save_users
from src.emailing import send_password_reset_email, send_verification_email
from src.nutrition import NutritionResult

from .progress import calorie_done_today


GMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9.+_-]*@gmail\.com$", re.IGNORECASE)
VERIFICATION_TOKEN_HOURS = 24
RESET_TOKEN_HOURS = 1


def init_state() -> None:
    """Siapkan database dan isi nilai awal seluruh kunci session_state yang dipakai aplikasi."""
    ensure_database()
    defaults = {
        "authenticated": False,
        "users": migrate_users(load_users()),
        "current_user": None,
        "page": "Login",
        "nutrition": None,
        "profile": None,
        "food_recommendations": None,
        # Kategori bahan utama yang sedang dipakai sebagai filter menu.
        # Menggantikan `meal_preference` (teks bebas) yang sudah tidak dipakai
        # sejak preferensi berubah jadi pilihan kategori.
        "meal_categories": [],
        "exercise_recommendations": None,
        "workout_filters": None,
        "selected_workout": None,
        "excluded_food_ids": [],
        "excluded_exercise_titles": [],
        # Penanda pemulihan hasil hari ini dari database (lihat
        # restore_today_menu / restore_today_workout di views/): tanggal
        # terakhir pencarian record dilakukan, dan apakah yang sedang tampil
        # berasal dari simpanan atau baru saja dibuat.
        "meal_restored_on": None,
        "workout_restored_on": None,
        "meal_from_storage": False,
        "workout_from_storage": False,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def migrate_users(users: dict) -> dict:
    """Lengkapi field akun lama (user_id, role, email, auth_provider, email_verified) lalu simpan bila ada yang berubah."""
    migrated = False
    for email, user in users.items():
        if "user_id" not in user:
            user["user_id"] = str(uuid4())
            migrated = True
        if "role" not in user:
            user["role"] = "user"
            migrated = True
        if "email" not in user:
            user["email"] = email
            migrated = True
        if "auth_provider" not in user or user.get("auth_provider") is None:
            user["auth_provider"] = "local"
            migrated = True
        if "email_verified" not in user or user.get("email_verified") is None:
            # Akun yang sudah ada sebelum fitur verifikasi email ada di-grandfather
            # sebagai verified, supaya user lama tidak mendadak ter-lock out.
            user["email_verified"] = True
            migrated = True
    if migrated:
        save_users(users)
    return users


def is_gmail_address(email: str) -> bool:
    """True bila alamat email berformat Gmail yang sah."""
    return bool(GMAIL_PATTERN.match((email or "").strip()))


def generate_token() -> str:
    """Buat token acak aman-URL untuk verifikasi email atau reset password."""
    return secrets.token_urlsafe(32)


def start_email_verification(email: str) -> None:
    """Buat token verifikasi baru untuk `email`, simpan, dan kirim emailnya."""
    st.session_state.users = migrate_users(load_users())
    user = st.session_state.users.get(email)
    if not user:
        return
    token = generate_token()
    user["verification_token"] = token
    user["verification_expires_at"] = (datetime.now() + timedelta(hours=VERIFICATION_TOKEN_HOURS)).isoformat(timespec="seconds")
    user["email_verified"] = False
    save_users(st.session_state.users)
    send_verification_email(email, user.get("name") or email, token)


def confirm_email_verification(token: str) -> tuple[bool, str]:
    """Tandai email sebagai terverifikasi kalau token valid & belum kedaluwarsa.
    Return (berhasil, pesan) supaya UI tinggal tampilkan pesannya."""
    if not token:
        return False, "Token verifikasi tidak ditemukan."
    st.session_state.users = migrate_users(load_users())
    for email, user in st.session_state.users.items():
        if user.get("verification_token") != token:
            continue
        expires_at = _parse_token_expiry(user.get("verification_expires_at"))
        if expires_at and expires_at < datetime.now():
            return False, "Token verifikasi sudah kedaluwarsa. Silakan daftar ulang atau minta verifikasi baru."
        user["email_verified"] = True
        user["verification_token"] = None
        user["verification_expires_at"] = None
        save_users(st.session_state.users)
        return True, "Email berhasil diverifikasi. Silakan login."
    return False, "Token verifikasi tidak valid."


def start_password_reset(email: str, base_url: str | None = None) -> tuple[bool, str]:
    """Buat token reset password & kirim emailnya kalau akun ditemukan.
    Selalu balas pesan yang sama baik akun ada atau tidak, supaya tidak bisa
    dipakai menebak-nebak email mana yang terdaftar (enumeration)."""
    st.session_state.users = migrate_users(load_users())
    generic_message = "Kalau email tersebut terdaftar, tautan reset password sudah dikirim. Silakan cek inbox Anda."
    user = st.session_state.users.get(email)
    # Akun lama berprovider "google" tetap boleh mengatur ulang kata sandi:
    # dikecualikan karena punya jalur login sendiri; setelah login Google
    # dihapus, reset password adalah satu-satunya cara mereka masuk lagi --
    # mengecualikannya di sini akan mengunci mereka keluar selamanya.
    if not user:
        return True, generic_message
    token = generate_token()
    user["reset_token"] = token
    user["reset_token_expires_at"] = (datetime.now() + timedelta(hours=RESET_TOKEN_HOURS)).isoformat(timespec="seconds")
    save_users(st.session_state.users)
    send_password_reset_email(email, user.get("name") or email, token, base_url=base_url)
    return True, generic_message


def confirm_password_reset(token: str, new_password: str) -> tuple[bool, str]:
    """Ganti password bila token reset valid dan belum kedaluwarsa; balas (berhasil, pesan)."""
    if not token:
        return False, "Token reset tidak ditemukan."
    st.session_state.users = migrate_users(load_users())
    for email, user in st.session_state.users.items():
        if user.get("reset_token") != token:
            continue
        expires_at = _parse_token_expiry(user.get("reset_token_expires_at"))
        if expires_at and expires_at < datetime.now():
            return False, "Token reset sudah kedaluwarsa. Silakan minta tautan reset yang baru."
        user["password"] = None
        user["password_hash"] = hash_password(new_password)
        user["reset_token"] = None
        user["reset_token_expires_at"] = None
        save_users(st.session_state.users)
        return True, "Password berhasil diubah. Silakan login dengan password baru Anda."
    return False, "Token reset tidak valid."


def _parse_token_expiry(value) -> datetime | None:
    """Baca waktu kedaluwarsa token jadi datetime tanpa timezone; None bila tidak terbaca."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    try:
        return datetime.fromisoformat(str(value)).replace(tzinfo=None)
    except ValueError:
        return None


def landing_page_for_user() -> str:
    """Halaman yang dibuka setelah pengguna berhasil masuk."""
    return "Home" if st.session_state.get("nutrition") else "Calorie Calculator"


# --------------------------------------------------------------------------- #
# Kata sandi
# --------------------------------------------------------------------------- #
# Hash memakai Argon2id dengan garam acak. Akun lama ber-hash SHA-256 masih bisa
# masuk lalu otomatis dimigrasi pada saat login, karena hanya di titik itulah
# aplikasi memegang kata sandi aslinya. Lihat docs/catatan-desain.md bagian 18.
_PASSWORD_HASHER = PasswordHasher(
    time_cost=2,
    memory_cost=19 * 1024,
    parallelism=1,
    hash_len=32,
    salt_len=16,
)

# Hash lama: SHA-256 heksadesimal 64 karakter, tanpa salt.
LEGACY_SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")


def hash_password(password: str) -> str:
    """Hash kata sandi baru dengan Argon2id (format PHC, sudah memuat salt & parameter)."""
    return _PASSWORD_HASHER.hash(password)


def legacy_sha256(password: str) -> str:
    """Skema lama. HANYA dipakai untuk memverifikasi akun yang belum dimigrasi."""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def stored_password_hash(user: dict) -> str | None:
    """Hash yang tersimpan untuk satu akun.

    Ada dua kolom karena sejarah: pendaftaran lama menulis ke `password`,
    sedangkan reset kata sandi menulis ke `password_hash`. `password_hash`
    diperiksa lebih dulu karena itulah kolom yang dipakai skema sekarang.
    """
    for field in ("password_hash", "password"):
        value = user.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def verify_password(user: dict, password: str) -> bool:
    """True bila kata sandi cocok dengan hash yang tersimpan.

    Menerima hash Argon2id maupun SHA-256 warisan; kata sandi polos ditolak.
    """
    stored = stored_password_hash(user)
    if not stored or not password:
        return False

    if stored.startswith("$argon2"):
        try:
            return _PASSWORD_HASHER.verify(stored, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

    if LEGACY_SHA256_PATTERN.match(stored):
        # compare_digest, bukan ==, supaya lama pembandingan tidak bergantung
        # pada berapa banyak karakter awal yang sudah cocok.
        return hmac.compare_digest(stored.lower(), legacy_sha256(password))

    return False


def password_needs_upgrade(user: dict) -> bool:
    """True kalau hash akun ini masih skema lama atau parameternya sudah ketinggalan."""
    stored = stored_password_hash(user)
    if not stored:
        return False
    if not stored.startswith("$argon2"):
        return True
    try:
        return _PASSWORD_HASHER.check_needs_rehash(stored)
    except InvalidHashError:
        return True


def upgrade_password_hash(email: str, password: str) -> None:
    """Ganti hash lama pengguna dengan Argon2id, lalu buang kolom hash warisannya."""
    users = migrate_users(load_users())
    user = users.get(email)
    if not user:
        return
    user["password_hash"] = hash_password(password)
    # Kolom lama dikosongkan supaya tidak ada dua sumber kebenaran yang bisa
    # berbeda -- dan supaya hash SHA-256-nya benar-benar hilang dari database.
    user["password"] = None
    save_users(users)
    st.session_state.users = users


def current_user() -> dict:
    """Data akun yang sedang login, dibaca ulang dari database setiap pemanggilan."""
    st.session_state.users = migrate_users(load_users())
    return st.session_state.users.get(st.session_state.current_user, {})


def current_role() -> str:
    """Role akun yang sedang login (default user)."""
    return current_user().get("role", "user")


def restore_user_context(email: str) -> None:
    """Pulihkan profil dan target nutrisi dari record terakhir, lalu bersihkan sisa sesi pengguna sebelumnya."""
    user = st.session_state.users.get(email, {})
    calorie_record = latest_user_record(CALORIE_STORE, user.get("user_id"))
    profile = calorie_record.get("profile") if calorie_record else user.get("profile")
    nutrition = calorie_record.get("nutrition") if calorie_record else user.get("nutrition")
    if profile and nutrition:
        st.session_state.profile = profile
        st.session_state.nutrition = NutritionResult(**nutrition)
    else:
        st.session_state.profile = None
        st.session_state.nutrition = None
    st.session_state.food_recommendations = None
    st.session_state.meal_categories = []
    st.session_state.exercise_recommendations = None
    st.session_state.workout_filters = None
    st.session_state.excluded_food_ids = []
    st.session_state.excluded_exercise_titles = []
    # Penanda pemulihan ikut dibersihkan: kalau tidak, user berikutnya yang
    # login di browser yang sama akan dianggap "sudah dicek hari ini" dan
    # menu/latihan miliknya tidak ikut dipulihkan.
    st.session_state.meal_restored_on = None
    st.session_state.workout_restored_on = None
    st.session_state.meal_from_storage = False
    st.session_state.workout_from_storage = False


# Kolom yang menentukan apakah dua perhitungan itu "sama". Kalau seluruhnya
# sama, hasil perhitungannya pasti sama juga -- BMR, TDEE, dan target kalori
# semuanya fungsi dari kolom-kolom ini.
PROFILE_IDENTITY_FIELDS = (
    "gender", "age", "weight_kg", "height_cm",
    "activity_level", "experience_level", "fitness_goal",
)


def _profile_identity(profile: dict) -> tuple:
    """Ringkas profil jadi tuple field penentu, untuk membandingkan dua perhitungan."""
    return tuple(profile.get(field) for field in PROFILE_IDENTITY_FIELDS)


def same_profile_today(profile: dict, user_id, *, today: date | None = None) -> bool:
    """Sudah pernahkah profil yang PERSIS sama dihitung hari ini?"""
    if not user_id:
        return False
    today = today or date.today()
    identity = _profile_identity(profile)
    for record in load_records(CALORIE_STORE) or []:
        if record.get("user_id") != user_id:
            continue
        stamp = str(record.get("created_at") or "")[:10]
        if stamp != today.isoformat():
            continue
        tersimpan = record.get("profile")
        if isinstance(tersimpan, dict) and _profile_identity(tersimpan) == identity:
            return True
    return False


def persist_user_profile(profile: dict, nutrition: NutritionResult) -> bool:
    """Simpan profil dan hasil gizi pengguna, lalu catat ke riwayat kalori.

    Balas False bila perhitungan dengan data yang sama persis sudah tercatat hari itu,
    sehingga riwayat tidak menumpuk entri kembar.
    """
    email = st.session_state.current_user
    if not email:
        return False
    st.session_state.users = migrate_users(load_users())
    user = st.session_state.users.get(email)
    if not user:
        return False
    user_id = user["user_id"]
    user["profile"] = profile
    user["nutrition"] = nutrition.__dict__
    save_users(st.session_state.users)

    if same_profile_today(profile, user_id):
        return False

    append_record(
        CALORIE_STORE,
        {
            "id": str(uuid4()),
            "user_id": user_id,
            "email": email,
            "profile": profile,
            "nutrition": nutrition.__dict__,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        },
    )
    return True


def persist_meal_recommendation(recommendations: dict, preference: list[str]) -> None:
    """Catat satu hasil rekomendasi menu beserta kategori bahan yang dipilih."""
    user = current_user()
    if not user:
        return
    append_record(
        MEAL_STORE,
        {
            "id": str(uuid4()),
            "user_id": user["user_id"],
            "email": user["email"],
            "preference": preference,
            "recommendations": recommendations,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        },
    )


def persist_workout_recommendation(recommendations: pd.DataFrame, filters: dict) -> None:
    """Catat satu hasil rekomendasi latihan beserta filter yang dipakai."""
    user = current_user()
    if not user:
        return
    append_record(
        WORKOUT_STORE,
        {
            "id": str(uuid4()),
            "user_id": user["user_id"],
            "email": user["email"],
            "filters": filters,
            "recommendations": recommendations.to_dict("records"),
            "created_at": datetime.now().isoformat(timespec="seconds"),
        },
    )


def parse_birth_date(value) -> date:
    """Baca tanggal lahir dari string atau date; jatuh ke 1 Januari 2000 bila tidak valid."""
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return date(2000, 1, 1)
    return date(2000, 1, 1)


def calculate_age_from_birth_date(birth_date: date, today: date | None = None, *, minimum: int = 0) -> int:
    """Hitung umur dari tanggal lahir, memperhitungkan apakah ulang tahun tahun ini sudah lewat."""
    today = today or date.today()
    birthday_passed = (today.month, today.day) >= (birth_date.month, birth_date.day)
    age = today.year - birth_date.year - (0 if birthday_passed else 1)
    return max(minimum, age)


def ensure_nutrition_ready() -> bool:
    """True bila data gizi pengguna sudah tersedia; bila belum, tampilkan pengarah ke Hitung Kalori."""
    if st.session_state.nutrition is None:
        st.info("Silakan hitung target nutrisi Anda terlebih dahulu.")
        if st.button("Buka Kalkulator Kalori"):
            st.session_state.page = "Calorie Calculator"
            st.rerun()
        return False

    if not calorie_done_today(current_user().get("user_id")):
        st.warning(
            "Hari baru dimulai. Selesaikan **Langkah 1: Hitung Kalori** hari ini "
            "supaya rekomendasi yang Anda terima memakai data terbaru."
        )
        if st.button("Hitung Kalori Sekarang", type="primary"):
            st.session_state.page = "Calorie Calculator"
            st.rerun()
        return False

    return True
