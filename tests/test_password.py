"""Uji hashing kata sandi Argon2id + migrasi dari SHA-256 lama."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from _isolasi import pakai_schema_uji  # noqa: E402

pakai_schema_uji("password")

from src.core.state import (  # noqa: E402
    hash_password,
    legacy_sha256,
    password_needs_upgrade,
    stored_password_hash,
    verify_password,
)

SANDI = "RahasiaKuat123!"

# --- Format hash baru ---
h = hash_password(SANDI)
print("hash baru:", h[:48], "...")
assert h.startswith("$argon2id$"), h
assert SANDI not in h, "kata sandi bocor di dalam hash"

# Salt acak: dua hash untuk kata sandi SAMA harus berbeda.
assert hash_password(SANDI) != hash_password(SANDI), "salt tidak acak"
print("salt acak: OK (dua hash kata sandi sama menghasilkan nilai berbeda)")

# --- Verifikasi ---
akun_baru = {"password_hash": h, "password": None}
assert verify_password(akun_baru, SANDI)
assert not verify_password(akun_baru, "salah")
assert not verify_password(akun_baru, "")
assert not verify_password({}, SANDI)
assert not verify_password({"password_hash": None, "password": None}, SANDI)
print("verifikasi argon2: OK")

# --- Akun lama: hash SHA-256 di kolom `password` (pola pendaftaran lama) ---
akun_lama = {"password": legacy_sha256(SANDI), "password_hash": None}
assert verify_password(akun_lama, SANDI), "akun lama tidak bisa login lagi"
assert not verify_password(akun_lama, "salah")
assert password_needs_upgrade(akun_lama)
assert not password_needs_upgrade(akun_baru)
print("kompatibilitas SHA-256 lama: OK")

# --- Kata sandi POLOS tidak boleh diterima lagi ---
akun_polos = {"password": SANDI, "password_hash": None}
assert not verify_password(akun_polos, SANDI), \
    "fallback kata sandi polos masih aktif — ini kerentanan yang seharusnya sudah ditutup"
print("fallback kata sandi polos: sudah ditutup")

# --- Prioritas kolom ---
assert stored_password_hash({"password_hash": "A", "password": "B"}) == "A"
assert stored_password_hash({"password_hash": None, "password": "B"}) == "B"
assert stored_password_hash({"password_hash": "  ", "password": "B"}) == "B"
assert stored_password_hash({}) is None
print("prioritas kolom password_hash > password: OK")

# --- Migrasi sungguhan lewat penyimpanan ---
from uuid import uuid4  # noqa: E402

from src.database import ensure_database, load_users, save_users  # noqa: E402
from src.core import state as S  # noqa: E402


class _SesiPalsu(dict):
    """Pengganti st.session_state supaya upgrade_password_hash bisa diuji tanpa Streamlit."""

    def __getattr__(self, name):
        """Baca kunci dict lewat notasi atribut, meniru st.session_state."""
        return self.get(name)

    def __setattr__(self, name, value):
        """Tulis kunci dict lewat notasi atribut, meniru st.session_state."""
        self[name] = value


S.st.session_state = _SesiPalsu()

ensure_database()
EMAIL = "lama@gmail.com"
save_users({EMAIL: {
    "user_id": str(uuid4()), "email": EMAIL, "name": "Akun Lama", "role": "user",
    "password": legacy_sha256(SANDI), "password_hash": None,
    "auth_provider": "local", "email_verified": True,
}})

user = load_users()[EMAIL]
assert password_needs_upgrade(user)
S.upgrade_password_hash(EMAIL, SANDI)

user = load_users()[EMAIL]
assert user["password_hash"].startswith("$argon2id$"), user["password_hash"]
assert user["password"] is None, "hash SHA-256 lama masih tertinggal di database"
assert not password_needs_upgrade(user)
assert verify_password(user, SANDI), "tidak bisa login setelah migrasi"
assert not verify_password(user, "salah")
print("migrasi otomatis saat login: OK (SHA-256 lama terhapus dari database)")

# Migrasi akun yang tidak ada tidak boleh melempar error.
S.upgrade_password_hash("tidak-ada@gmail.com", SANDI)

print("\nSEMUA ASSERT PASSWORD LOLOS")
