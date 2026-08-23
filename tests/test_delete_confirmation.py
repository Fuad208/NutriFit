"""Uji konfirmasi penghapusan riwayat: data hanya terhapus setelah pengguna menegaskan."""
import os
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from _isolasi import pakai_schema_uji  # noqa: E402

pakai_schema_uji("hapus")

from datetime import datetime, timedelta  # noqa: E402

import pandas as pd  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

from src import recommender as R  # noqa: E402

# Dataset dibaca dari CSV, bukan dari database: schema uji di atas hanya berisi
# tabel aplikasi, sedangkan halaman ini tetap butuh dataset untuk dirender.
# Latihan dibatasi 200 baris supaya pencocokan tutorial yang O(n*m) tidak
# memperlambat pengujian -- yang diuji di sini soal konfirmasi hapus, bukan
# kualitas rekomendasi.
R.check_image_urls_concurrently = lambda urls, max_workers=20: [True] * len(urls)
_members = pd.read_csv(ROOT / "data" / "gym_members.csv")
_foods = pd.read_csv(ROOT / "data" / "food_nutrition.csv")
_ex = pd.read_csv(ROOT / "data" / "training_program.csv").head(200)
R.load_dataset_tables = lambda: (_members, _foods, _ex)

from src.core.state import hash_password  # noqa: E402
from src.database import (  # noqa: E402
    CALORIE_STORE,
    ensure_database,
    load_records,
    save_records,
    save_users,
)

ensure_database()

EMAIL = "uji.hapus@contoh.test"
USER_ID = str(uuid4())


def catatan(target: float, mundur_hari: int) -> dict:
    """Satu catatan perhitungan kalori milik user uji."""
    waktu = datetime.now() - timedelta(days=mundur_hari)
    return {
        "id": str(uuid4()),
        "user_id": USER_ID,
        "email": EMAIL,
        "profile": {
            "gender": "Male", "age": 22, "weight_kg": 70.0, "height_cm": 175.0,
            "activity_level": "Medium", "experience_level": "Intermediate",
            "fitness_goal": "Lose Weight", "bmi": 22.9,
        },
        "nutrition": {
            "bmi": 22.9, "bmi_status": "Normal", "bmr": 1674, "tdee": 2008,
            "target_calories": target, "protein_g": 154, "fat_g": 42,
            "carbohydrate_g": 200, "ideal_weight": 67.5,
        },
        "created_at": waktu.isoformat(timespec="seconds"),
    }


LAMA, BARU = catatan(1800, 3), catatan(1900, 1)
save_users({EMAIL: {
    "user_id": USER_ID, "email": EMAIL, "name": "Uji Hapus",
    "password_hash": hash_password("rahasia"), "role": "user",
    "birth_date": "2004-01-01", "gender": "Male",
}})
save_records(CALORIE_STORE, [LAMA, BARU])


def buka():
    """Buka halaman Hitung Kalori sebagai pengguna uji yang sudah login."""
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=300)
    at.session_state["authenticated"] = True
    at.session_state["current_user"] = EMAIL
    at.session_state["page"] = "Calorie Calculator"
    return at.run()


def jumlah() -> int:
    """Banyaknya catatan kalori milik pengguna uji yang tersisa di penyimpanan."""
    return len([r for r in load_records(CALORIE_STORE) if r.get("user_id") == USER_ID])


def tombol_hapus(at) -> list:
    """Daftar key tombol hapus yang muncul pada halaman."""
    return [b.key for b in at.button if str(b.key or "").startswith("delete_calorie_")]


print("== dua catatan disiapkan ==")
assert jumlah() == 2, jumlah()
print(f"   {jumlah()} catatan di schema uji {os.environ['POSTGRES_SCHEMA']}")

print("\n== menekan Hapus TIDAK boleh langsung menghapus ==")
at = buka()
kunci = tombol_hapus(at)
assert len(kunci) == 2, f"tombol hapus per baris: {len(kunci)}"
at.button(key=kunci[0]).click().run()
assert not at.exception, [e.value for e in at.exception]
assert jumlah() == 2, f"data terhapus tanpa konfirmasi! sisa {jumlah()}"
print("   ditekan sekali, catatan tetap 2 -- menunggu konfirmasi")

print("\n== dialog konfirmasi memuat peringatan yang benar ==")
sisa_tombol = [b.key for b in at.button]
assert "calorie_delete_confirm" in sisa_tombol, sisa_tombol
assert "calorie_delete_cancel" in sisa_tombol, sisa_tombol
teks = " ".join((m.value or "") for m in at.markdown).lower()
assert "permanen" in teks, "tidak menyebut penghapusan bersifat permanen"
peringatan = " ".join((w.value or "") for w in at.warning).lower()
assert "target kalori" in peringatan, f"tidak memperingatkan dampak ke target: {peringatan[:120]}"
print("   ada tombol Batal & Ya, sebut 'permanen', dan peringatkan dampak ke target kalori")

print("\n== Batal benar-benar membatalkan ==")
at.button(key="calorie_delete_cancel").click().run()
assert not at.exception, [e.value for e in at.exception]
assert jumlah() == 2, f"Batal malah menghapus! sisa {jumlah()}"
assert not [b.key for b in at.button if b.key == "calorie_delete_confirm"], "dialog tidak tertutup"
print("   catatan tetap 2, dialog tertutup")

print("\n== Ya, Hapus baru benar-benar menghapus ==")
at = buka()
at.button(key=tombol_hapus(at)[0]).click().run()
at.button(key="calorie_delete_confirm").click().run()
assert not at.exception, [e.value for e in at.exception]
assert jumlah() == 1, f"seharusnya tersisa 1, dapat {jumlah()}"
tersisa = [r for r in load_records(CALORIE_STORE) if r.get("user_id") == USER_ID][0]
assert tersisa["id"] == LAMA["id"], "baris yang terhapus bukan yang dipilih"
print(f"   catatan terbaru terhapus, tersisa 1 (target {tersisa['nutrition']['target_calories']} kkal)")

print("\n== pesan sukses muncul setelah dialog tertutup ==")
sukses = " ".join((s.value or "") for s in at.success).lower()
assert "berhasil dihapus" in sukses, f"tidak ada konfirmasi keberhasilan: {sukses[:100]}"
print("   'Transaksi kalori berhasil dihapus.'")

print("\n== menghapus catatan TERAKHIR diperingatkan lebih keras ==")
at = buka()
at.button(key=tombol_hapus(at)[0]).click().run()
peringatan = " ".join((w.value or "") for w in at.warning).lower()
assert "satu-satunya" in peringatan, f"tidak memperingatkan ini catatan terakhir: {peringatan[:140]}"
assert "kosong" in peringatan, "tidak menjelaskan targetnya akan kosong"
print("   diperingatkan target & makro akan kosong dan rekomendasi tidak bisa dibuat")

print("\nSEMUA ASSERT KONFIRMASI HAPUS LOLOS")
